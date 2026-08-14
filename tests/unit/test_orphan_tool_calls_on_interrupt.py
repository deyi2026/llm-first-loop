"""验证：run_stream 客户端中断（close）后是否产生孤儿 tool_calls.

背景：借鉴 DeepSeek Harness「取消时写合成结果，不留半截工具链」。
本项目时序：assistant 声明（带全部 tool_calls）先 append 进 in-memory sess + 事件日志
→ yield tool_round → 最后 execute_many 补 tool 回执。若客户端在 yield 阶段 close：

- JSON 读路径（默认 read_path_source=session_json）：JSON 仅在 run 结束 save()，
  中断前只走事件日志 → 下一轮 load 到旧 JSON → 在途消息静默丢失；
- event_log 读路径（D1 退役终态）：replay 重建出「有声明、无回执」的孤儿声明
  → 下一轮请求带孤儿 tool_calls，严格 FC 协议会 400。

本测试只做事实验证，不做修复。
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


def test_json_path_interrupt_silent_loss(build_test_engine, tmp_path):
    """场景A（当前默认 JSON 读路径）：中断后在途消息是否落盘。"""
    engine, _ = build_test_engine([])
    engine.llm_pool.default_client = _StreamFake()
    sid = engine.session.create()

    _interrupt_at_tool_round(engine, sid)

    msgs = engine.session.load(sid).messages
    declared, answered, orphans = _orphan_report(msgs)
    print(f"\n[A-JSON] 消息总数: {len(msgs)} 声明: {sorted(declared)} 回执: {sorted(answered)} 孤儿: {sorted(orphans)}")
    # 事实：JSON 未在中间 save → 在途消息（user + assistant 声明）全部丢失
    assert len(msgs) == 0, "场景A事实：JSON 读路径下中断 → 在途消息未落盘，静默丢失"


def test_event_log_path_interrupt_orphans(build_test_engine, tmp_path):
    """场景B（event_log 读路径，D1 终态）：中断后 replay 出孤儿声明并原样发给 LLM。"""
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
    assert orphans == {"c1", "c2"}, "场景B事实：event_log 读路径中断 → replay 出 2 个孤儿 tool_calls"

    # 下一轮请求：history.py 协议配对自检（L560+）在请求构建时补齐诚实占位
    # → FC 400 风险已有兜底（借鉴点1的协议风险假设被驳回）
    for _ in engine.run_stream(sid, "continue please"):
        pass
    sent = fake.calls[-1]["messages"]
    sent_decl = [m for m in sent if isinstance(m, dict) and m.get("tool_calls")]
    sent_tools = [m for m in sent if isinstance(m, dict) and m.get("role") == "tool"]
    print(f"[B-EVT] 下一轮请求: 孤儿声明消息 {len(sent_decl)} 条, 占位 tool 回执 {len(sent_tools)} 条")
    assert sent_decl, "孤儿声明仍在历史里"
    assert sent_tools and all("工具回执缺失" in t.get("content", "") for t in sent_tools), \
        "配对自检补齐了诚实占位回执 → 严格 FC 不 400（已有兜底）"

    # 残留事实：占位只补在出站请求，不回写会话 → 孤儿永久残留，每轮重复告警补齐
    msgs_after = engine.session.load(sid).messages
    _, _, orphans_after = _orphan_report(msgs_after)
    print(f"[B-EVT] 补齐不回写会话，孤儿仍残留: {sorted(orphans_after)}")
    assert orphans_after == {"c1", "c2"}, "配对自检不回写历史，孤儿声明永久残留"
