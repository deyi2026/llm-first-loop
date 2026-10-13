"""Phase6 M1：同步 chat 通道窗口内打断（设计 §3A，TDD red→green）。

- S1 窗口内插话：即时消费（consumed_via=sync_window_poll）+ 下一轮真实消费插话
  + 被打断轮文本不进下一轮 provider 投影（P1-6 退役纪律）。
- S2 窗口内 Stop：即时终态（_CANCELLED_ANSWER，0 字节 0 工具），不等 worker。
- S3 配置门关（sync_chat_interject_checkpoint=False）：回退 final_gate 窗口形态。
- S4 窗口内多插话：全量消费（P1-3 批量口径）。
- S5 worker 异常透传：与内联异常行为一致（error 事件）。
- S6 协作取消钩子：带 cancel() 的 client 在打断时被调用（M2 web client 契约）。
"""
from __future__ import annotations

import contextlib
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from llm_loop.core.loop.runner import BackgroundRunner  # noqa: E402
from llm_loop.llm.client import LLMError, LLMResponse  # noqa: E402
from llm_loop.web import build_app  # noqa: E402
from tests.phase4.test_m0_scenarios import (  # noqa: E402
    INTERJECT_TEXT,
    _hq_item,
    _hq_of,
    _interject,
    _wait_run_done,
)

WINDOW_S = 1.2
INJECT_AT_S = 0.3
SYNC_FULL = "SYNC-FULL-ANSWER-PLACEHOLDER"


def _blocking(window_started: threading.Event, window_s: float = WINDOW_S):
    def _item(_calls) -> LLMResponse:
        window_started.set()
        time.sleep(window_s)
        return LLMResponse(content=SYNC_FULL, tool_calls=[], provider="fake")
    return _item


def _start_sync_run(build_test_engine, responses):
    engine, fake = build_test_engine(responses)
    runner = BackgroundRunner(engine)
    engine.runner = runner
    client = TestClient(build_app(engine=engine))
    sid = engine.session.create()
    return engine, fake, runner, client, sid


def _inject_during_window(client, runner, sid):
    gen = (runner.get_handle(sid) or {}).get("run_generation")
    r1 = client.post(
        "/api/v1/chat/queue",
        json={"session_id": sid, "message": INTERJECT_TEXT},
    )
    assert r1.status_code == 202
    queue_id = r1.json()["queue_id"]
    r2 = _interject(client, sid, queue_id, gen)
    assert r2.status_code == 202
    return queue_id


def test_s1_sync_window_interject_interrupted(build_test_engine):
    """窗口内插话 → 即时消费 + 下一轮消费插话 + 打断轮不进投影."""
    window_started = threading.Event()
    engine, fake, runner, client, sid = _start_sync_run(
        build_test_engine,
        [
            _blocking(window_started),
            {"content": "final-after-interject"},
        ],
    )
    _h, q = runner.start(sid, "请长篇回答")
    assert window_started.wait(timeout=10)
    time.sleep(INJECT_AT_S)
    t_inject = time.monotonic()
    queue_id = _inject_during_window(client, runner, sid)
    final = _wait_run_done(q, timeout=30)
    t_done = time.monotonic()
    assert final.get("type") == "done"
    item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
    assert item.get("status") == "interject_received"
    assert item.get("consumed_via") == "sync_window_poll", item
    t_effect = (item["received_at"] - item["created_at"]) * 1000.0
    assert t_effect <= 300.0, f"S1 t_effect 应即时（≤300ms），实测 {t_effect:.1f}ms"
    # run 总时长不含残余窗口等待：打断后下一轮立即发起新调用
    assert (t_done - t_inject) < WINDOW_S - INJECT_AT_S + 1.0, "打断后不应等待完整残余窗口才结束"
    # 下一轮真实消费插话；打断轮文本不进下一轮 provider 投影（P1-6）
    assert len(fake.calls) >= 2, f"应有两轮调用，实际 {len(fake.calls)}"
    msgs2 = fake.calls[1]["messages"]
    joined = "\n".join(str(m.get("content", "")) for m in msgs2)
    assert INTERJECT_TEXT in joined, "下一轮请求历史应含插话文本"
    assert SYNC_FULL not in joined, "被打断轮的响应文本不得进入下一轮 provider 投影"


def test_s2_sync_window_stop_prompt(build_test_engine):
    """窗口内 Stop → 即时终态（不等 worker 残余）."""
    window_started = threading.Event()
    engine, fake, runner, client, sid = _start_sync_run(
        build_test_engine, [_blocking(window_started)]
    )
    _h, q = runner.start(sid, "请长篇回答")
    assert window_started.wait(timeout=10)
    time.sleep(INJECT_AT_S)
    t0 = time.monotonic()
    runner.cancel(sid)
    final = _wait_run_done(q, timeout=30)
    stop_effect = (time.monotonic() - t0) * 1000.0
    assert final.get("type") == "done"
    assert stop_effect <= 400.0, f"S2 Stop 应即时（≤400ms），实测 {stop_effect:.1f}ms"
    # 四态口径：取消在途 → 终态 0 字节 0 工具（_CANCELLED_ANSWER 语义）
    _fa2 = getattr(final.get("result"), "final_answer", "") or final.get("final_answer", "")
    assert "已停止" in str(_fa2) or str(_fa2) == "", f"终答应为取消语义，实际: {_fa2!r}"


def test_s3_gate_off_falls_back_to_final_gate(build_test_engine, monkeypatch):
    """sync_chat_interject_checkpoint=False → 回退窗口形态（final_gate）."""
    window_started = threading.Event()
    engine, fake, runner, client, sid = _start_sync_run(
        build_test_engine,
        [
            _blocking(window_started),
            {"content": "final-after-interject"},
        ],
    )
    # frozen dataclass 实例字段直改（engine 读取的是实例 settings.tool_runtime）
    _tr = engine.settings.tool_runtime
    _orig_gate = _tr.sync_chat_interject_checkpoint
    object.__setattr__(_tr, "sync_chat_interject_checkpoint", False)
    try:
        _h, q = runner.start(sid, "请长篇回答")
        assert window_started.wait(timeout=10)
        time.sleep(INJECT_AT_S)
        queue_id = _inject_during_window(client, runner, sid)
        final = _wait_run_done(q, timeout=30)
        assert final.get("type") == "done"
        item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
        assert item.get("consumed_via") == "final_gate", item
    finally:
        object.__setattr__(_tr, "sync_chat_interject_checkpoint", _orig_gate)


def test_s4_multiple_interjections_all_consumed(build_test_engine):
    """窗口内多插话 → 全量进入下一轮（P1-3 批量口径）."""
    window_started = threading.Event()
    engine, fake, runner, client, sid = _start_sync_run(
        build_test_engine,
        [
            _blocking(window_started),
            {"content": "final-after-multi"},
        ],
    )
    _h, q = runner.start(sid, "请长篇回答")
    assert window_started.wait(timeout=10)
    time.sleep(INJECT_AT_S)
    queue_ids = []
    for text in (INTERJECT_TEXT, "第二条插话内容-请并入"):
        gen = (runner.get_handle(sid) or {}).get("run_generation")
        r1 = client.post(
            "/api/v1/chat/queue", json={"session_id": sid, "message": text}
        )
        assert r1.status_code == 202
        qid = r1.json()["queue_id"]
        r2 = _interject(client, sid, qid, gen)
        assert r2.status_code == 202
        queue_ids.append(qid)
    final = _wait_run_done(q, timeout=30)
    assert final.get("type") == "done"
    msgs2 = fake.calls[1]["messages"]
    joined = "\n".join(str(m.get("content", "")) for m in msgs2)
    assert INTERJECT_TEXT in joined and "第二条插话内容-请并入" in joined, joined


def test_s5_worker_exception_propagates(build_test_engine):
    """worker 内 provider 异常 → 与内联异常一致（error 事件）."""
    def _boom(_calls) -> LLMResponse:
        raise LLMError("fake sync provider failure")
    engine, fake, runner, client, sid = _start_sync_run(build_test_engine, [_boom])
    _h, q = runner.start(sid, "请长篇回答")
    final = _wait_run_done(q, timeout=15)
    assert final.get("type") in ("done", "error"), final
    # 供者错误如实归因（error 事件或终答含错误语义——与内联异常同口径）
    _fa = getattr(final.get("result"), "final_answer", "") or final.get("final_answer", "")
    assert final.get("type") == "error" or "异常" in str(_fa)


def test_s6_cancel_hook_invoked(build_test_engine):
    """带 cancel() 钩子的 client：打断时钩子被调用（M2 契约）."""
    window_started = threading.Event()
    engine, fake, runner, client, sid = _start_sync_run(
        build_test_engine,
        [
            _blocking(window_started),
            {"content": "final-after-hook"},
        ],
    )
    hooked = []
    fake.cancel = lambda: hooked.append(time.monotonic())  # 协作取消钩子
    _h, q = runner.start(sid, "请长篇回答")
    assert window_started.wait(timeout=10)
    time.sleep(INJECT_AT_S)
    _inject_during_window(client, runner, sid)
    _wait_run_done(q, timeout=30)
    assert hooked, "client.cancel() 钩子应在打断时被调用"


# ── 设计 §8 评审回填：R1 单次结算 / R5 工具轮打断 / R6 竞态命中优先 ──────


class _SpyCallCoordinator:
    """R1 专用最小协调器：只记录 open/settle，不接 journal。"""

    def __init__(self):
        self.opens: list[object] = []
        self.settles: list[tuple[object, str]] = []

    def open_shadow_call_for_client(self, _client, **_):
        ident = object()
        self.opens.append(ident)
        return ident

    def bind_shadow_call_site(self, _call, _client, **_):
        return contextlib.nullcontext()

    def lease_for_client(self, _client, **_):
        return contextlib.nullcontext()

    def settle_shadow_call(self, call, outcome):
        self.settles.append((call, str(getattr(outcome, "value", outcome))))

    def last_provider_attempt_id(self, _call):
        return ""


def test_s7_interrupt_settles_exactly_once(build_test_engine):
    """R1：打断轮恰好一次 INTERRUPTED 结算；晚到 worker 响应无二次结算路径。"""
    window_started = threading.Event()
    spy = _SpyCallCoordinator()
    engine, fake, runner, client, sid = _start_sync_run(
        build_test_engine,
        [
            _blocking(window_started),
            {"content": "final-after-single-settle"},
        ],
    )
    engine.provider_call_coordinator = spy
    _h, q = runner.start(sid, "请长篇回答")
    assert window_started.wait(timeout=10)
    time.sleep(INJECT_AT_S)
    queue_id = _inject_during_window(client, runner, sid)
    final = _wait_run_done(q, timeout=30)
    assert final.get("type") == "done"
    item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
    assert item.get("consumed_via") == "sync_window_poll", item
    outcomes = [o for (_c, o) in spy.settles]
    assert outcomes.count("interrupted") == 1, f"应恰好一次 INTERRUPTED 结算: {outcomes}"
    # 单次结算语义：同一 provider_call 不被结算第二次（晚到结果只作孤儿，不重开）
    seen: dict[int, str] = {}
    for call, outcome in spy.settles:
        key = id(call)
        assert key not in seen, f"provider_call {key} 被重复结算: {seen[key]} -> {outcome}"
        seen[key] = outcome
    assert "success" in seen.values(), "下一轮（消费插话后）应正常 success 结算"


def test_s8_tool_round_interrupt_skips_execution(build_test_engine):
    """R5：工具轮窗口打断——响应含 tool_calls 也不执行，下一轮只消费插话。"""
    from llm_loop.core.message import ToolResult, ToolResultStatus

    executed: list[float] = []

    class _SpyTool:
        name = "phase6_spy_tool"
        description = "Phase6 M1 R5 断言：记录是否被打断轮执行"
        parameters = {"type": "object", "properties": {}, "required": []}

        def execute(self, **_):
            executed.append(time.monotonic())
            return ToolResult(status=ToolResultStatus.SUCCESS, content="spy-done")

    window_started = threading.Event()

    def _tool_item(_calls) -> LLMResponse:
        window_started.set()
        time.sleep(WINDOW_S)
        return LLMResponse(
            content="",
            tool_calls=[{"id": "c1", "name": "phase6_spy_tool", "arguments": {}}],
            provider="fake",
        )

    engine, fake, runner, client, sid = _start_sync_run(
        build_test_engine,
        [
            _tool_item,
            {"content": "final-after-tool-interrupt"},
        ],
    )
    engine.registry.register(_SpyTool())
    _h, q = runner.start(sid, "请调用测试工具")
    assert window_started.wait(timeout=10)
    time.sleep(INJECT_AT_S)
    queue_id = _inject_during_window(client, runner, sid)
    final = _wait_run_done(q, timeout=30)
    assert final.get("type") == "done"
    assert executed == [], "打断轮的 tool_calls 不得执行"
    item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
    assert item.get("consumed_via") == "sync_window_poll", item
    msgs2 = fake.calls[1]["messages"]
    joined = "\n".join(str(m.get("content", "")) for m in msgs2)
    assert INTERJECT_TEXT in joined, "下一轮请求历史应含插话文本"


def test_s9_interjection_wins_over_completed_worker(build_test_engine):
    """R6：竞态命中优先——worker 已完成但窗口内插话可见时，打断仍生效。

    确定性构造：包装 runner.interjections_pending，使插话仅在 worker 完成后
    对轮询可见。检查顺序必须先看插话再看 worker 存活——否则回退为完整响应。
    """
    window_started = threading.Event()
    worker_done = threading.Event()

    def _item(_calls) -> LLMResponse:
        window_started.set()
        time.sleep(INJECT_AT_S + 0.5)
        worker_done.set()
        return LLMResponse(content=SYNC_FULL, tool_calls=[], provider="fake")

    engine, fake, runner, client, sid = _start_sync_run(
        build_test_engine,
        [
            _item,
            {"content": "final-after-race"},
        ],
    )
    _orig_pending = runner.interjections_pending
    runner.interjections_pending = (
        lambda s: worker_done.is_set() and _orig_pending(s)
    )
    _h, q = runner.start(sid, "请长篇回答")
    assert window_started.wait(timeout=10)
    time.sleep(INJECT_AT_S)  # 窗口内注入（此刻轮询尚不可见）
    queue_id = _inject_during_window(client, runner, sid)
    final = _wait_run_done(q, timeout=30)
    assert final.get("type") == "done"
    item = _hq_item(_hq_of(client, engine), sid, queue_id) or {}
    assert item.get("consumed_via") == "sync_window_poll", (
        "命中优先：即使 worker 已完成，窗口内插话仍应打断"
    )
    msgs2 = fake.calls[1]["messages"]
    joined = "\n".join(str(m.get("content", "")) for m in msgs2)
    assert INTERJECT_TEXT in joined
    assert SYNC_FULL not in joined, "已完成 worker 的响应应被丢弃，不进下一轮 provider 投影"
