"""Phase4 M2 在途打断：CK-B 分段等待 + CK-C 单调用粒度定向取消 + 竞速判别.

对应 docs/phase4-effect-latency-design.md §4.2 CK-B/C、§4.3、§4.4：
- S13-M2 达标：2.0s 长工具 + 0.3s 注入 → 定向终止收割 → t_effect P50≤500/P95≤1000
- S14 保守等待：revocable=False（且非闭集）工具不被打断，自然边界回执
- S15 竞速双分支：事件序判定（回执标注真值），两分支各≥3 次如实
- gate 保守矩阵（§4.4）：stop 优先/无 peek/闭集外/副作用面 → 全 False
- 停止四态零变化：stop 与打断并存时 stop 链接管（unit 级断言 gate=False）
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from llm_loop.core.loop.runner import BackgroundRunner
from llm_loop.core.message import ToolCall
from llm_loop.web import build_app
from tests.phase4.test_m0_scenarios import (
    INTERJECT_TEXT,
    _hq_item,
    _hq_of,
    _interject,
    _LockedSleepTool,
    _pct,
    _wait_run_done,
    _wait_tool_started,
)

REPO_DIR = None

M2_REPORT_DIR = Path(
    os.environ.get("PHASE4_M2_REPORT_DIR", "reports/phase4/m2")
)
M2_REPORT_DIR = Path(os.path.abspath(M2_REPORT_DIR))
M2_REPORT_DIR.mkdir(parents=True, exist_ok=True)



def _guarded_write(path, *a, **k):
    """基线/里程碑快照防覆写护栏（同 M0 惯例；PHASE4_OVERWRITE_REPORTS=1 强制）."""
    import os as _os
    if path.exists() and _os.environ.get("PHASE4_OVERWRITE_REPORTS") != "1":
        return
    return path.write_text(*a, **k)

def _one_interrupt_sample(build_test_engine, i: int) -> dict:
    engine, fake = build_test_engine(
        [
            {
                "content": "跑长命令",
                "tool_calls": [
                    ToolCall(id=f"s13m2-{i}-c1", name="execute_command",
                             arguments={"command": "sleep 2.0"}),
                ],
            },
            {"content": "final-after-interrupt"},
        ]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    t0 = time.perf_counter()
    try:
        _h, q = runner.start(sid, "请执行长命令")
        assert _wait_tool_started(engine, "execute_command", "_active_procs")
        time.sleep(0.3)
        gen = (runner.get_handle(sid) or {}).get("run_generation")
        r1 = client.post(
            "/api/v1/chat/queue",
            json={"session_id": sid, "message": INTERJECT_TEXT},
        )
        assert r1.status_code == 202
        queue_id = r1.json()["queue_id"]
        r2 = _interject(client, sid, queue_id, gen)
        assert r2.status_code == 202

        final = _wait_run_done(q, timeout=30)
        elapsed = time.perf_counter() - t0
        item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
        c, r = item.get("created_at"), item.get("received_at")
        t_effect = round((r - c) * 1000, 1) if c and r else None
        sess = engine.session.load(sid)
        texts = [m.content or "" for m in sess.messages]
        return {
            "tag": f"S13M2-{i+1}", "t_effect_ms": t_effect,
            "elapsed_s": round(elapsed, 2), "final": final.get("type"),
            "item_status": item.get("status"),
            "interrupted_receipt": any("interrupted_for_interjection" in t for t in texts),
            "model_saw_interject": any(INTERJECT_TEXT in t for t in texts),
            "receipt_texts": [t[:120] for t in texts if "interrupted_for_interjection" in t],
        }
    finally:
        runner.cancel(sid)


def test_a_s13_interrupt_meets_target(build_test_engine):
    samples = []
    for i in range(5):
        s = _one_interrupt_sample(build_test_engine, i)
        # 每样本断言：打断回执存在 + 终态正常 + 模型可见 + 总时长显著短于自然完成
        assert s["interrupted_receipt"], f"应存在在途打断回执: {s}"
        assert s["final"] == "done"
        assert s["model_saw_interject"]
        assert s["elapsed_s"] < 1.8, f"应被打断（elapsed={s['elapsed_s']}s）: {s}"
        samples.append(s)
    effs = [s["t_effect_ms"] for s in samples if s["t_effect_ms"] is not None]
    p50, p95 = _pct(effs, 0.50), _pct(effs, 0.95)
    _guarded_write(M2_REPORT_DIR / "S13M2.json",
        json.dumps({"scenario": "S13M2", "n": 5, "samples": samples,
                    "t_effect_p50_ms": p50, "t_effect_p95_ms": p95},
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    assert p50 is not None and p50 <= 500.0, f"S13-M2 P50={p50}ms 超 500ms"
    assert p95 is not None and p95 <= 1000.0, f"S13-M2 P95={p95}ms 超 1000ms"


def test_b_s14_conservative_wait(build_test_engine):
    """不可中断（revocable=False + 非闭集）：保守等待自然边界，零打断."""
    samples = []
    for i in range(3):
        engine, fake = build_test_engine(
            [
                {
                    "content": "跑锁定工具",
                    "tool_calls": [
                        ToolCall(id=f"s14m2-{i}-c1", name="phase4_locked_sleep",
                                 arguments={"seconds": 2.0}),
                    ],
                },
                {"content": "final-conservative"},
            ]
        )
        engine.registry.register(_LockedSleepTool())
        runner = BackgroundRunner(engine)
        engine.runner = runner
        client = TestClient(build_app(engine=engine))
        sid = engine.session.create()
        try:
            _h, q = runner.start(sid, "请执行锁定任务")
            assert _wait_tool_started(engine, "phase4_locked_sleep", "_active")
            time.sleep(0.3)
            gen = (runner.get_handle(sid) or {}).get("run_generation")
            r1 = client.post(
                "/api/v1/chat/queue",
                json={"session_id": sid, "message": INTERJECT_TEXT},
            )
            queue_id = r1.json()["queue_id"]
            r2 = _interject(client, sid, queue_id, gen)
            assert r2.status_code == 202

            final = _wait_run_done(q, timeout=30)
            item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
            c, r = item.get("created_at"), item.get("received_at")
            sess = engine.session.load(sid)
            texts = [m.content or "" for m in sess.messages]
            samples.append({
                "tag": f"S14M2-{i+1}",
                "t_effect_ms": round((r - c) * 1000, 1) if c and r else None,
                "final": final.get("type"),
                "natural_receipt": any("locked sleep done" in t for t in texts),
                "interrupted_receipt": any("interrupted_for_interjection" in t for t in texts),
            })
            # 断言：自然完成回执在、打断回执绝不在、终态正常
            assert samples[-1]["natural_receipt"], samples[-1]
            assert not samples[-1]["interrupted_receipt"], samples[-1]
            assert samples[-1]["final"] == "done"
        finally:
            runner.cancel(sid)
    effs = [s["t_effect_ms"] for s in samples if s["t_effect_ms"] is not None]
    _guarded_write(M2_REPORT_DIR / "S14M2.json",
        json.dumps({"scenario": "S14M2", "n": 3, "samples": samples,
                    "t_effect_p50_ms": _pct(effs, 0.50)},
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def test_c_s15_race_two_branches(build_test_engine):
    """竞速双分支：事件序判定=回执标注真值；构造上分支可控（τ=200ms 量化）."""
    samples = []
    # 分支 B（interrupt_first）：注入 +1.25s（早于 1.4s 判定片）→ sleep 1.5 被终止
    for i in range(3):
        samples.append(_race_sample(build_test_engine, i, "B", inject_delay=1.25))
    # 分支 A（natural_first，终局加固）：sleep 1.55 + 注入 +1.45s——完成时刻落在
    # 判定片 (1.4,1.6) 内部：到达无论何时（轻载 1.46-1.51 / 重载 >1.55），下一
    # 判定唤醒 1.6s 均晚于完成 1.55s，future.result 先返自然结果，双侧确定性
    # 落入自然完成分支（不与判定片边界对齐——1.6 会在完成点与唤醒点赛跑）。
    for i in range(3):
        samples.append(_race_sample(build_test_engine, i, "A", inject_delay=1.45,
                                    tool_sleep=1.55))
    for s in samples:
        assert s["final"] == "done"
        assert s["item_status"] == "interject_received"
        if s["construct"] == "B":
            assert s["branch"] == "interrupt_first", s
            assert s["interrupted_receipt"]
        else:
            assert s["branch"] == "natural_first", s
            assert not s["interrupted_receipt"]
    _guarded_write(M2_REPORT_DIR / "S15M2.json",
        json.dumps({"scenario": "S15M2", "n": len(samples), "samples": samples},
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _race_sample(build_test_engine, i: int, construct: str, inject_delay: float,
                 tool_sleep: float = 1.5) -> dict:
    engine, fake = build_test_engine(
        [
            {
                "content": "跑竞速命令",
                "tool_calls": [
                    ToolCall(id=f"s15m2-{construct}-{i}-c1", name="execute_command",
                             arguments={"command": f"sleep {tool_sleep}"}),
                ],
            },
            {"content": "final-race"},
        ]
    )
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    try:
        _h, q = runner.start(sid, "请执行命令")
        assert _wait_tool_started(engine, "execute_command", "_active_procs")
        time.sleep(inject_delay)
        gen = (runner.get_handle(sid) or {}).get("run_generation")
        r1 = client.post(
            "/api/v1/chat/queue",
            json={"session_id": sid, "message": INTERJECT_TEXT},
        )
        queue_id = r1.json()["queue_id"]
        r2 = _interject(client, sid, queue_id, gen)
        assert r2.status_code == 202
        final = _wait_run_done(q, timeout=30)
        item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
        c, r = item.get("created_at"), item.get("received_at")
        sess = engine.session.load(sid)
        texts = [m.content or "" for m in sess.messages]
        interrupted = any("interrupted_for_interjection" in t for t in texts)
        return {
            "construct": construct, "tag": f"S15M2-{construct}-{i+1}",
            "inject_delay_s": inject_delay,
            "t_effect_ms": round((r - c) * 1000, 1) if c and r else None,
            "final": final.get("type"), "item_status": item.get("status"),
            "interrupted_receipt": interrupted,
            # 事件序判定：回执标注即真值（registry 同线程串行判定）
            "branch": "interrupt_first" if interrupted else "natural_first",
        }
    finally:
        runner.cancel(sid)


def test_d_gate_conservative_matrix(build_test_engine):
    """§4.4 gate 保守矩阵（unit）：各失败面 → False；全清 → True."""
    # run 需存活整个断言期（handle status=running 是 peek/enqueue 的前提）：
    # 单轮即完的 run 会让后续断言与 handle 清理赛跑（全套负载下必现）。
    # 存活工具用内联纯 sleep——不登记 revocable=False 副作用（locked 工具会登记
    # 且永不 settle，负载下登记先于断言落账 →「已结算后恢复 True」被自身工具污染）。
    class _PlainSleepTool:
        name = "phase4_plain_sleep"
        description = "test_d 专用：纯 sleep 保活，无副作用登记"
        parameters = {"type": "object",
                      "properties": {"seconds": {"type": "number"}},
                      "required": ["seconds"]}

        def execute(self, seconds: float = 5.0) -> str:
            time.sleep(seconds)
            return "plain sleep done"

    engine, fake = build_test_engine([
        {"content": "go", "tool_calls": [
            ToolCall(id="gate-matrix-c1", name="phase4_plain_sleep",
                     arguments={"seconds": 5.0})]},
        {"content": "ok"},
    ])
    engine.registry.register(_PlainSleepTool())
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()
    gate = engine._phase4_interrupt_gate
    try:
        _h, q = runner.start(sid, "ping")
        gen = (runner.get_handle(sid) or {}).get("run_generation")
        # 1) 无 peek → False
        assert gate(sid, "execute_command") is False
        # 2) peek 真值 + 闭集 + 无副作用 → True
        assert runner.enqueue_interjection(
            sid, {"message": "hi"}, expected_run_generation=gen
        ) is True
        assert gate(sid, "execute_command") is True
        # 3) 闭集外 → False
        assert gate(sid, "phase4_locked_sleep") is False
        # 4) 未结算 revocable=False 副作用 → False（登记前重置代次 contextvar：
        #    本用例在 run 上下文外直接登记，it_gen 应为空（=保守阻断语义）；
        #    全套下 main 线程残留其他用例的代次会造成跨 run 误判（污染源））
        from llm_loop.core.loop.side_effects import SideEffectRegistry
        from llm_loop.core.run_context import current_run_generation
        current_run_generation.set("")
        ser = SideEffectRegistry.instance()
        ser.register(sid, "t", "a", "k", revocable=False, detail="gate-matrix")
        try:
            assert gate(sid, "execute_command") is False
        finally:
            snap = ser.snapshot(sid)
            for it in snap:
                if it.get("detail") == "gate-matrix":
                    ser.settle(it.get("id"), reason="gate-matrix-test")
        # 已结算后恢复 True
        assert gate(sid, "execute_command") is True
        # 5) stop 链优先：cancel_reason 非空 → False（stop 通道接管）
        orig = runner.cancel_reason
        runner.cancel_reason = lambda _sid: "user_stop"  # type: ignore[assignment]
        try:
            assert gate(sid, "execute_command") is False
        finally:
            runner.cancel_reason = orig  # type: ignore[assignment]
        assert gate(sid, "execute_command") is True
        # 6) gate 抛异常路径（引擎侧兜底）→ 不在此测（registry 侧 except 覆盖）
    finally:
        runner.cancel(sid)


# ────────────────────────────────────────────────────────────────────
# P1-3（M2 审查）：打断发生后停止通道零触碰的运行级专项断言
# ────────────────────────────────────────────────────────────────────
def test_p1_3_interrupt_touches_no_stop_channel(build_test_engine):
    from llm_loop.core.loop.side_effects import SideEffectRegistry

    engine, fake = build_test_engine([
        {"content": "go",
         "tool_calls": [ToolCall(id="p13-c1", name="execute_command",
                                 arguments={"command": "sleep 2.0"})]},
        {"content": "final-p13"},
    ])
    hook_calls: list[str] = []
    engine.registry.add_session_cancel_hook(
        lambda *a, **k: hook_calls.append("cancel_hook")
    )
    ser = SideEffectRegistry.instance()
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    try:
        _h, q = runner.start(sid, "run")
        assert _wait_tool_started(engine, "execute_command", "_active_procs")
        time.sleep(0.3)
        gen = (runner.get_handle(sid) or {}).get("run_generation")
        r1 = client.post("/api/v1/chat/queue",
                         json={"session_id": sid, "message": INTERJECT_TEXT})
        queue_id = r1.json()["queue_id"]
        assert _interject(client, sid, queue_id, gen).status_code == 202
        final = _wait_run_done(q, timeout=30)

        assert final.get("type") == "done"
        sess = engine.session.load(sid)
        texts = [m.content or "" for m in sess.messages]
        assert any("interrupted_for_interjection" in t for t in texts), "打断应发生"
        # 三不断言 1：会话取消钩子零触发
        assert hook_calls == [], f"session cancel hooks 被误触: {hook_calls}"
        # 三不断言 2：停止记录零写入（stop_record 空 = 无 record_stop_requested）
        rec = ser.stop_record(sid) or {}
        assert not rec.get("requested_at"), f"StopRecord 被误写: {rec}"
        # 三不断言 3：终态 done 而非 cancelled/stopped（会话级连坐未发生）
        assert (runner.get_handle(sid) or {}).get("status") in (None, "done", "idle")
    finally:
        runner.cancel(sid)


# ────────────────────────────────────────────────────────────────────
# P2-6（M2 审查）：打断→剩余调用 skipped_for_interjection 接续 + 轮内消费
# ────────────────────────────────────────────────────────────────────
def test_p2_6_interrupt_skips_remaining_calls(build_test_engine):
    engine, fake = build_test_engine([
        {"content": "两条长命令",
         "tool_calls": [
             ToolCall(id="p26-c1", name="execute_command",
                      arguments={"command": "sleep 2.0"}),
             ToolCall(id="p26-c2", name="execute_command",
                      arguments={"command": "sleep 2.0"}),
         ]},
        {"content": "final-p26"},
    ])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    t0 = time.perf_counter()
    try:
        _h, q = runner.start(sid, "run")
        assert _wait_tool_started(engine, "execute_command", "_active_procs")
        time.sleep(0.3)
        gen = (runner.get_handle(sid) or {}).get("run_generation")
        r1 = client.post("/api/v1/chat/queue",
                         json={"session_id": sid, "message": INTERJECT_TEXT})
        queue_id = r1.json()["queue_id"]
        assert _interject(client, sid, queue_id, gen).status_code == 202
        final = _wait_run_done(q, timeout=30)
        elapsed = time.perf_counter() - t0

        assert final.get("type") == "done"
        sess = engine.session.load(sid)
        texts = [m.content or "" for m in sess.messages]
        # c1 在途打断回执 + c2 skipped 回执，均存在且各一条
        assert sum(1 for t in texts if "interrupted_for_interjection" in t) == 1
        skips = [t for t in texts if "skipped_for_interjection" in t]
        assert len(skips) == 1, skips
        # c2 未被执行：无第二条命令的自然完成回执（部分输出回执仅 1 条）
        assert sum(1 for t in texts if "[退出码 0]" in t and "sleep 2.0" in t) == 0
        # 接续路径整体时延：0.3 注入 + τ(0.2) 判定 + 收割 + 轮转 << 4.0s 自然
        assert elapsed < 1.8, f"打断+接续应显著快于双 2.0s: {elapsed:.2f}s"
        item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
        c, r = item.get("created_at"), item.get("received_at")
        assert item.get("status") == "interject_received"
        t_effect = (r - c) * 1000 if c and r else None
        assert t_effect is not None and t_effect < 900.0, t_effect
    finally:
        runner.cancel(sid)
