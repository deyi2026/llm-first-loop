"""HARNESS-01 回归守卫：run_stream 客户端中断（close）后的孤儿 tool_calls 兜底.

演化史：
- 初版（2026-08-15 早）实测确认缺口：中断 → 孤儿声明 / JSON 路径静默丢失
- 并行会话同日实现 HARNESS-01 修复（tool_exec.py +88 行）：
  GeneratorExit 时 _synthesize_cancelled 写合成"已取消"回执 + 立即 save，
  对账不变量「声明数 = 结果数 + 取消数」成立
- 本文件随之翻转为回归守卫：断言修复后行为（无孤儿、消息完整落盘）
"""

from __future__ import annotations

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse, StreamDelta


class _StreamFake:
    """流式 Fake：第一轮返回 2 个只读工具调用，后续轮返回文本。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.model = "fake-model"
        self.timeout_s = 120.0
        self.thinking_mode = True
        self.reasoning_effort = "high"
        self.thinking_supported = True
        self._round = 0

    def chat(self, messages, tools, *, timeout_s=None, model=None) -> LLMResponse:
        self.calls.append({"messages": list(messages), "model": model})
        return LLMResponse(content="sync", tool_calls=[], provider="fake")

    def chat_stream(self, messages, tools, *, timeout_s=None, model=None):
        self.calls.append({"messages": list(messages), "model": model})
        self._round += 1
        if self._round == 1:
            resp = LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="c1", name="read_file", arguments={"path": "/tmp/a.txt"}),
                    ToolCall(id="c2", name="read_file", arguments={"path": "/tmp/b.txt"}),
                ],
                provider="fake",
            )
        else:
            resp = LLMResponse(content="done", tool_calls=[], provider="fake")
        for ch in (resp.content or ""):
            yield StreamDelta(text=ch)
        return resp


def _interrupt_at_tool_round(engine, sid: str) -> None:
    gen = engine.run_stream(sid, "read two files")
    saw_tool_round = False
    for d in gen:
        if getattr(d, "tool_round", None) is not None:
            saw_tool_round = True
            break
    assert saw_tool_round, "应在 execute_many 之前看到 tool_round 分片"
    gen.close()  # 模拟客户端断流


def _orphan_report(msgs) -> tuple[set, set, set]:
    declared = {tc["id"] for m in msgs if m.role == "assistant" for tc in (m.tool_calls or [])}
    answered = {m.tool_call_id for m in msgs if m.role == "tool"}
    return declared, answered, declared - answered


def test_json_path_interrupt_no_orphan_no_loss(build_test_engine):
    """场景A（JSON 读路径）：中断后无孤儿、在途消息完整落盘（HARNESS-01 回归守卫）。"""
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = _StreamFake()
    sid = engine.session.create()

    _interrupt_at_tool_round(engine, sid)

    msgs = engine.session.load(sid).messages
    declared, answered, orphans = _orphan_report(msgs)
    print(f"\n[A-JSON] 消息总数: {len(msgs)} 声明: {sorted(declared)} 回执: {sorted(answered)} 孤儿: {sorted(orphans)}")
    assert not orphans, "HARNESS-01：中断后不得有孤儿 tool_calls"
    assert declared == {"c1", "c2"} and answered == {"c1", "c2"}, "声明与合成取消回执成对落盘"
    assert any(m.role == "user" for m in msgs), "在途用户消息不得静默丢失"
    cancel_msgs = [m for m in msgs if m.role == "tool"]
    assert all("中断" in m.content or "取消" in m.content for m in cancel_msgs), "合成回执须诚实标注"


def test_event_log_path_interrupt_no_orphan(build_test_engine, tmp_path):
    """场景B（event_log 读路径）：中断后 replay 历史自洽，下一轮正常继续。"""
    from llm_loop.core.session import SessionStore
    from llm_loop.event_log.store import EventStore

    engine, _ = build_test_engine([])
    fake = _StreamFake()
    engine.llm_pool.default_client = fake

    store = EventStore(tmp_path / "event_logs", enabled=True)
    engine.session = SessionStore(
        tmp_path / "sessions", event_store=store, read_path_source="event_log"
    )
    engine._event_store = store

    sid = engine.session.create()
    _interrupt_at_tool_round(engine, sid)

    msgs = engine.session.load(sid).messages
    declared, answered, orphans = _orphan_report(msgs)
    print(f"\n[B-EVT] 消息总数: {len(msgs)} 声明: {sorted(declared)} 回执: {sorted(answered)} 孤儿: {sorted(orphans)}")
    assert not orphans, "HARNESS-01：event_log replay 后不得有孤儿"

    # 下一轮：历史自洽 → 正常继续，无配对自检兜底告警路径
    for _ in engine.run_stream(sid, "continue please"):
        pass
    assert fake.calls[-1]["messages"], "下一轮请求正常构建"
    msgs_after = engine.session.load(sid).messages
    _, _, orphans_after = _orphan_report(msgs_after)
    assert not orphans_after, "继续对话后历史保持自洽"
