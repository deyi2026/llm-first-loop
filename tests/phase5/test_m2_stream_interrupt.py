"""Phase5 M2：LLM 流内插话打断（S17-M1/M2/M3/M4 + S18-M3 跨轮复位）。

设计依据：docs/phase5-stream-interrupt-design.md（r2）§2.2/§4。
确定性构造（评审 Q4）：FakeLLM.enable_stream 的 on_delta_n 钩子在产 delta 的
next() 内同步完成注入（queue→interject→ack 落盘），钩子返回后同一 delta 的
流内检查点必然命中（节流 40ms < delta_delay 50ms）——无真实时钟竞态。
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from llm_loop.core.loop.runner import BackgroundRunner  # noqa: E402
from llm_loop.web import build_app  # noqa: E402
from tests.phase4.test_m0_scenarios import (  # noqa: E402
    INTERJECT_TEXT,
    _hq_item,
    _hq_of,
    _interject,
    _wait_run_done,
)

STREAM_FULL = "STREAM-COMPLETE-ANSWER-PLACEHOLDER-FOR-INTERRUPT-ROUND"
STREAM_FINAL = "final-after-interrupt"


def _deltas(n: int = 20) -> list[str]:
    return [f"流片段{i}。" for i in range(n)]


class _Injector:
    """跨线程确定性注入：run 线程 hook 只发就绪信号并阻塞等注入完成；
    主线程完成 queue→interject（ack 落盘）后放行——钩子返回后同一 delta
    的流内检查点必然命中。避免 run 线程内 TestClient 调用（portal 死锁）。"""

    def __init__(self, client, sid, runner):
        self._client = client
        self._sid = sid
        self._runner = runner
        self._ready = threading.Event()
        self._injected = threading.Event()
        self.cancel_after = False
        self.queue_id = None
        self.injected_at = None

    def inject_now(self) -> None:
        """主线程直接注入（工具场景，无需流钩子同步）。"""
        gen = (self._runner.get_handle(self._sid) or {}).get("run_generation")
        r1 = self._client.post(
            "/api/v1/chat/queue",
            json={"session_id": self._sid, "message": INTERJECT_TEXT},
        )
        assert r1.status_code == 202
        self.queue_id = r1.json()["queue_id"]
        r2 = _interject(self._client, self._sid, self.queue_id, gen)
        assert r2.status_code == 202, f"插话受理非 202: {r2.status_code}"
        self.injected_at = time.monotonic()

    def hook(self, _i: int) -> None:
        self._ready.set()
        assert self._injected.wait(timeout=10), "主线程注入超时（hook 放行失败）"

    def run_inject(self) -> None:
        """主线程调用：等 run 线程到达注入 delta → 注入（可选 stop）→ 放行。"""
        assert self._ready.wait(timeout=10), "流未到达注入 delta"
        gen = (self._runner.get_handle(self._sid) or {}).get("run_generation")
        r1 = self._client.post(
            "/api/v1/chat/queue",
            json={"session_id": self._sid, "message": INTERJECT_TEXT},
        )
        assert r1.status_code == 202, f"入队非 202: {r1.status_code}"
        self.queue_id = r1.json()["queue_id"]
        r2 = _interject(self._client, self._sid, self.queue_id, gen)
        assert r2.status_code == 202, f"插话受理非 202: {r2.status_code}"
        self.injected_at = time.monotonic()
        if self.cancel_after:
            self._runner.cancel(self._sid)
        self._injected.set()


def test_a_s17m1_m2_stream_interrupt(build_test_engine):
    """S17-M1/M2：流内打断生效+半截语义（P1-6 如实标注、不进下轮请求历史）。"""
    engine, fake = build_test_engine(
        [{"content": STREAM_FULL}, {"content": STREAM_FINAL}]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    inj = _Injector(client, sid, runner)
    fake.enable_stream(
        {
            "deltas": _deltas(20),
            "delta_delay_s": 0.05,
            "on_delta_n": {3: inj.hook},
        }
    )
    try:
        _h, q = runner.start(sid, "请长篇回答")
        inj.run_inject()
        final = _wait_run_done(q, timeout=30)
        assert final.get("type") == "done"

        # S17-M1：打断收割戳记与时延门
        item = _hq_item(_hq_of(client, engine), sid, inj.queue_id) or {}
        assert item.get("status") == "interject_received"
        assert item.get("consumed_via") == "llm_stream_interrupt"
        assert item.get("interrupt_receipt") is not True, "新桶 interrupt_receipt 恒 False"
        _c, _r = item.get("created_at"), item.get("received_at")
        assert _c and _r, f"hq 条目缺时间戳: {sorted(item.keys())}"
        te = (_r - _c) * 1000.0
        assert te <= 500.0, f"打断生效 t_effect={te:.1f}ms 应≤500ms"

        # S17-M2：半截行如实落盘（llm_interrupted 标注、内容=已生成部分）
        sess = engine.session.load(sid)
        halves = [
            m for m in sess.messages
            if getattr(m, "metadata", None) and m.metadata.get("llm_interrupted")
        ]
        assert halves, "半截行必须落盘（P1-6 不伪装完整）"
        half_text = (halves[-1].content or "")
        assert "流片段" in half_text and "流片段19" not in half_text
        assert STREAM_FULL not in half_text, "半截行不得含完整响应占位文本"

        # S17-M2：下一轮 LLM 请求历史含插话 user 文本、不含半截片段（B1 退役纪律）
        assert len(fake.calls) >= 2
        next_msgs = fake.calls[1]["messages"]
        joined = "".join(
            str(m.get("content") or "") if isinstance(m, dict) else str(getattr(m, "content", "") or "")
            for m in next_msgs
        )
        assert INTERJECT_TEXT in joined, "下一轮请求历史必须含插话 user 消息"
        assert "流片段" not in joined, "半截行不得进入下一轮 provider 历史（退役纪律）"
    finally:
        runner.cancel(sid)


def test_b_s17m3_stop_priority(build_test_engine):
    """S17-M3：stop 优先——同窗 stop+插话 → cancelled 接管，插话不被收割消费。"""
    engine, fake = build_test_engine([{"content": STREAM_FULL}])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    inj = _Injector(client, sid, runner)
    fake.enable_stream(
        {
            "deltas": _deltas(20),
            "delta_delay_s": 0.05,
            "on_delta_n": {3: inj.hook},
        }
    )
    try:
        inj.cancel_after = True
        _h, q = runner.start(sid, "请长篇回答")
        inj.run_inject()
        final = _wait_run_done(q, timeout=30)
        res = final.get("result")
        # runner 终报 type 恒 done；cancelled 语义=run_incomplete+终答占位（实测）
        assert getattr(res, "run_incomplete", False) is True and "已停止" in str(
            getattr(res, "final_answer", "")
        ), "stop 必须接管（流内取消优先于插话收割）"
        sess = engine.session.load(sid)
        halves = [
            m for m in sess.messages
            if getattr(m, "metadata", None) and m.metadata.get("llm_interrupted")
        ]
        assert halves, "stop 路径半截产物照常落盘（P1-6）"
        item = _hq_item(_hq_of(client, engine), sid, inj.queue_id) or {}
        assert item.get("status") != "interject_received", (
            "stop 接管时插话不得被流内收割消费（run 结束回滚/重投语义不变）"
        )
    finally:
        runner.cancel(sid)


def test_c_s17m4_conservative_off(build_test_engine, monkeypatch):
    """S17-M4：检查点开关关闭 → 保守 final_gate 路径（桶=llm_stream）不回归。"""
    engine, fake = build_test_engine([{"content": STREAM_FULL}])
    object.__setattr__(
        engine.settings.tool_runtime, "llm_stream_interject_checkpoint", False
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    inj = _Injector(client, sid, runner)
    fake.enable_stream(
        {
            "deltas": _deltas(12),
            "delta_delay_s": 0.04,
            "on_delta_n": {4: inj.hook},
        }
    )
    try:
        _h, q = runner.start(sid, "请长篇回答")
        inj.run_inject()
        final = _wait_run_done(q, timeout=30)
        assert final.get("type") == "done"
        item = _hq_item(_hq_of(client, engine), sid, inj.queue_id) or {}
        assert item.get("status") == "interject_received"
        assert item.get("consumed_via") == "final_gate", "关闭开关必须回退保守路径"
        # 流自然结束：完整响应为终答（无半截行）
        sess = engine.session.load(sid)
        halves = [
            m for m in sess.messages
            if getattr(m, "metadata", None) and m.metadata.get("llm_interrupted")
        ]
        assert not halves, "保守路径不得产生半截行"
    finally:
        runner.cancel(sid)


def test_d_s18m3_cross_run_reset(build_test_engine, monkeypatch):
    """S18-M3：跨 run 残值复位——run1 工具打断（置 True）→ run2 保守
    final_gate 消费 interrupt_receipt 必须 False（轮首复位 P2-5）。
    开关关闭（保守路径）确保 run2 插话走 final_gate 消费而非流内收割。"""
    from llm_loop.core.message import ToolCall
    from tests.phase4.test_m0_scenarios import _wait_tool_started

    engine, fake = build_test_engine(
        [
            {   # run1 轮1：打断 c1 + c2 skipped（置位 True 后收割）
                "content": "run1 两条命令",
                "tool_calls": [
                    ToolCall(id="s18m3-c1", name="execute_command",
                             arguments={"command": "sleep 2.0"}),
                    ToolCall(id="s18m3-c2", name="execute_command",
                             arguments={"command": "sleep 0.8"}),
                ],
            },
            {"content": "run1-final"},
            {"content": "run2-full-stream-answer"},
        ]
    )
    object.__setattr__(
        engine.settings.tool_runtime, "llm_stream_interject_checkpoint", False
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    inj1 = _Injector(client, sid, runner)
    inj2 = _Injector(client, sid, runner)
    try:
        # run1：c1 在途注入（CK-C 打断）→ 轮内 gap 收割 interrupt_receipt=True
        _h1, q1 = runner.start(sid, "run1")
        assert _wait_tool_started(engine, "execute_command", "_active_procs")
        inj1.inject_now()
        f1 = _wait_run_done(q1, timeout=30)
        assert f1.get("type") == "done"
        item1 = _hq_item(_hq_of(client, engine), sid, inj1.queue_id) or {}
        assert item1.get("consumed_via") == "gap_harvest"
        assert item1.get("interrupt_receipt") is True, "run1 打断事实"

        # run2：流式自然结束（开关关闭不收割）→ final_gate 消费；
        # run1 残值 True 必须被 run2 轮首复位消除（否则错标 interruptible 桶）
        fake.enable_stream(
            {"deltas": _deltas(12), "delta_delay_s": 0.04, "on_delta_n": {4: inj2.hook}}
        )
        _h2, q2 = runner.start(sid, "run2")
        inj2.run_inject()
        f2 = _wait_run_done(q2, timeout=30)
        assert f2.get("type") == "done"
        item2 = _hq_item(_hq_of(client, engine), sid, inj2.queue_id) or {}
        assert item2.get("consumed_via") == "final_gate"
        assert item2.get("interrupt_receipt") is not True, (
            "run2 final_gate 消费不得读到 run1 跨 run 残值 True（P2-5 轮首复位）"
        )
    finally:
        runner.cancel(sid)

