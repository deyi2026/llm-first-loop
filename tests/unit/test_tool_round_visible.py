"""P2-1 流式期间工具调用可见后端契约单测（tasks 4.1/4.2/4.3/4.4）."""

from __future__ import annotations

from llm_loop.core.message import ToolCall
from llm_loop.llm.client import LLMResponse, StreamDelta, ToolRoundInfo


def test_stream_delta_tool_round_default_none():
    """4.1: StreamDelta.tool_round 默认 None 向后兼容。"""
    d = StreamDelta(text="hello")
    assert d.tool_round is None
    assert d.reasoning is None
    assert d.text == "hello"


def test_stream_delta_tool_round_set():
    """4.1: StreamDelta.tool_round 可携带工具轮次进展。"""
    info = ToolRoundInfo(tool_name="read_file", round_index=1)
    d = StreamDelta(text="", tool_round=info)
    assert d.tool_round is not None
    assert d.tool_round.tool_name == "read_file"
    assert d.tool_round.round_index == 1
    assert d.text == ""


def test_tool_round_info_defaults():
    """4.2: ToolRoundInfo args_summary/tool_call_id 默认空字符串。"""
    info = ToolRoundInfo(tool_name="read_file", round_index=1)
    assert info.tool_name == "read_file"
    assert info.round_index == 1
    assert info.args_summary == ""
    assert info.tool_call_id == ""


def test_tool_round_info_full():
    """4.2: ToolRoundInfo 全字段构造。"""
    info = ToolRoundInfo(
        tool_name="search_records",
        round_index=3,
        args_summary='{"kind": "memory"}',
        tool_call_id="call_abc",
    )
    assert info.tool_name == "search_records"
    assert info.round_index == 3
    assert info.args_summary == '{"kind": "memory"}'
    assert info.tool_call_id == "call_abc"


def test_tool_args_summary_dict():
    """4.3: dict 参数 JSON 序列化。"""
    from llm_loop.core.loop.engine import _tool_args_summary

    s = _tool_args_summary({"path": "/tmp/file.txt"})
    assert "path" in s
    assert "/tmp/file.txt" in s


def test_tool_args_summary_truncation():
    """4.3: 超 200 字符截断附 "…"。"""
    from llm_loop.core.loop.engine import _tool_args_summary

    long_args = {"data": "x" * 300}
    s = _tool_args_summary(long_args)
    assert len(s) == 201  # 200 + "…"
    assert s.endswith("…")


def test_tool_args_summary_non_dict():
    """4.3: 非 dict 参数降级 str() 截断。"""
    from llm_loop.core.loop.engine import _tool_args_summary

    s = _tool_args_summary("just a string")
    assert s == "just a string"
    s2 = _tool_args_summary(42)
    assert s2 == "42"


def test_tool_args_summary_empty():
    """4.3: 空参数返回安全形式。"""
    from llm_loop.core.loop.engine import _tool_args_summary

    s = _tool_args_summary({})
    assert s == "{}"


class _MultiRoundStreamFake:
    """多轮流式 FakeLLM：按序列依次返回不同响应（支持工具轮次测试）。"""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.model = "fake-model"
        self.timeout_s = 120.0
        self.thinking_mode = True
        self.reasoning_effort = "high"
        self.thinking_supported = True

    def chat(self, messages, tools, *, timeout_s=None, model=None) -> LLMResponse:
        self.calls.append({"messages": messages, "model": model})
        return self._responses.pop(0) if self._responses else LLMResponse(content="", tool_calls=[], provider="fake")

    def chat_stream(self, messages, tools, *, timeout_s=None, model=None):
        self.calls.append({"messages": messages, "model": model})
        resp = self._responses.pop(0) if self._responses else LLMResponse(content="", tool_calls=[], provider="fake")
        for ch in (resp.content or ""):
            yield StreamDelta(text=ch)
        return resp


def _collect_deltas(gen) -> list[StreamDelta]:
    """消费 run_stream 生成器，收集所有 StreamDelta。"""
    deltas = []
    while True:
        try:
            d = next(gen)
            deltas.append(d)
        except StopIteration:
            break
    return deltas


def test_run_stream_yields_tool_round(build_test_engine, tmp_path):
    """4.4: run_stream 在工具轮次 yield tool_round 分片。"""
    f = tmp_path / "test.txt"
    f.write_text("content", encoding="utf-8")

    engine, _ = build_test_engine([])
    fake = _MultiRoundStreamFake([
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": str(f)})], provider="fake"),
        LLMResponse(content="done", tool_calls=[], provider="fake"),
    ])
    engine.llm_pool.default_client = fake

    sid = engine.session.create()
    deltas = _collect_deltas(engine.run_stream(sid, "read test.txt"))

    tool_round_deltas = [d for d in deltas if d.tool_round is not None]
    assert len(tool_round_deltas) == 1
    info = tool_round_deltas[0].tool_round
    assert info is not None
    assert info.tool_name == "read_file"
    assert info.round_index == 1
    assert info.tool_call_id == "c1"
    assert "path" in info.args_summary


def test_run_stream_no_tool_round_without_tool_calls(build_test_engine):
    """4.4: 无工具调用时不 yield tool_round（零回归）。"""
    engine, _ = build_test_engine([])
    fake = _MultiRoundStreamFake([LLMResponse(content="hello", tool_calls=[], provider="fake")])
    engine.llm_pool.default_client = fake

    sid = engine.session.create()
    deltas = _collect_deltas(engine.run_stream(sid, "hi"))

    tool_round_deltas = [d for d in deltas if d.tool_round is not None]
    assert len(tool_round_deltas) == 0


def test_run_stream_multi_round_tool_round(build_test_engine, tmp_path):
    """4.4: 多轮工具调用 yield 多次 tool_round，round_index 递增。"""
    f1 = tmp_path / "a.txt"
    f1.write_text("A", encoding="utf-8")
    f2 = tmp_path / "b.txt"
    f2.write_text("B", encoding="utf-8")

    engine, _ = build_test_engine([])
    fake = _MultiRoundStreamFake([
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": str(f1)})], provider="fake"),
        LLMResponse(content="", tool_calls=[ToolCall(id="c2", name="read_file", arguments={"path": str(f2)})], provider="fake"),
        LLMResponse(content="done", tool_calls=[], provider="fake"),
    ])
    engine.llm_pool.default_client = fake

    sid = engine.session.create()
    deltas = _collect_deltas(engine.run_stream(sid, "read a and b"))

    tool_round_deltas = [d for d in deltas if d.tool_round is not None]
    assert len(tool_round_deltas) == 2
    assert tool_round_deltas[0].tool_round is not None
    assert tool_round_deltas[1].tool_round is not None
    assert tool_round_deltas[0].tool_round.round_index == 1
    assert tool_round_deltas[1].tool_round.round_index == 2


def test_run_stream_multi_tool_call_same_round(build_test_engine, tmp_path):
    """4.4: 一轮多个 tool_call 各 yield 一次 tool_round。"""
    f1 = tmp_path / "a.txt"
    f1.write_text("A", encoding="utf-8")
    f2 = tmp_path / "b.txt"
    f2.write_text("B", encoding="utf-8")

    engine, _ = build_test_engine([])
    fake = _MultiRoundStreamFake([
        LLMResponse(content="", tool_calls=[
            ToolCall(id="c1", name="read_file", arguments={"path": str(f1)}),
            ToolCall(id="c2", name="read_file", arguments={"path": str(f2)}),
        ], provider="fake"),
        LLMResponse(content="done", tool_calls=[], provider="fake"),
    ])
    engine.llm_pool.default_client = fake

    sid = engine.session.create()
    deltas = _collect_deltas(engine.run_stream(sid, "read a and b"))

    tool_round_deltas = [d for d in deltas if d.tool_round is not None]
    assert len(tool_round_deltas) == 2
    assert tool_round_deltas[0].tool_round is not None
    assert tool_round_deltas[1].tool_round is not None
    assert tool_round_deltas[0].tool_round.tool_call_id == "c1"
    assert tool_round_deltas[1].tool_round.tool_call_id == "c2"
    assert tool_round_deltas[0].tool_round.round_index == 1
    assert tool_round_deltas[1].tool_round.round_index == 1


# ── HARNESS-01: 中断时孤儿 tool_calls 合成回执 ──


def test_interrupt_synthesizes_cancelled_results(tmp_path):
    """流式中断（GeneratorExit）→ 未执行声明合成取消回执并落盘（防孤儿→下轮 400）."""
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.tools.registry import ToolRegistry

    executed = []

    class _Fake:
        def __init__(self) -> None:
            self.calls = 0

        def _next(self):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    content="用工具",
                    tool_calls=[
                        ToolCall(id="tc-orphan", name="read_file", arguments={"path": "x"})
                    ],
                    provider="fake",
                )
            return LLMResponse(content="不会到", tool_calls=[], provider="fake")

        def chat(self, messages, tools, **kw):
            return self._next()

        def chat_stream(self, messages, tools, **kw):
            def _gen():
                yield from ()
                return self._next()

            return _gen()

    class _Reg(ToolRegistry):
        def execute(self, call):
            executed.append(call.id)
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="ok",
                tool_call_id=call.id,
                tool_name=call.name,
                duration_ms=0.0,
            )

    reg = _Reg()
    reg.register(
        type(
            "RF",
            (),
            {"name": "read_file", "description": "t", "parameters": {"type": "object"}},
        )()
    )
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    store = SessionStore(tmp_path / "sessions")
    engine = LoopEngine(
        llm_client=_Fake(),  # type: ignore[arg-type]
        registry=reg,  # type: ignore[arg-type]
        memory=None,  # type: ignore[arg-type]
        session=store,
        settings=settings,
    )
    sid = store.create()
    it = engine.run_stream(sid, "任务")
    # 消费第一个 delta（tool_round yield 处）后中断
    next(it)
    it.close()  # GeneratorExit → 合成回执
    assert executed == []  # 工具未执行
    sess = store.load(sid)
    tool_msgs = [m for m in sess.messages if m.role == "tool"]
    assert len(tool_msgs) == 1  # 合成取消回执
    assert "执行中断" in tool_msgs[0].content
    assert tool_msgs[0].tool_call_id == "tc-orphan"
    # 对账: 声明数 == 结果数(0) + 取消数(1)
    decl = [m for m in sess.messages if m.role == "assistant" and m.tool_calls]
    assert len(decl) == 1
    assert len(tool_msgs) == len(decl[0].tool_calls or [])


def test_reconciliation_missing_result_synthesized(tmp_path, monkeypatch):
    """正常路径对账：execute_many 缺结果 → 缺失声明合成取消（不变量成立）."""
    from llm_loop.config import Settings
    from llm_loop.core.loop.engine import LoopEngine
    from llm_loop.core.message import ToolCall, ToolResult, ToolResultStatus
    from llm_loop.core.session import SessionStore
    from llm_loop.llm.client import LLMResponse
    from llm_loop.tools.registry import ToolRegistry

    class _Fake:
        def __init__(self) -> None:
            self.calls = 0

        def _next(self):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    content="用工具",
                    tool_calls=[
                        ToolCall(id="tc-a", name="read_file", arguments={"path": "a"}),
                        ToolCall(id="tc-b", name="read_file", arguments={"path": "b"}),
                    ],
                    provider="fake",
                )
            return LLMResponse(content="最终回答", tool_calls=[], provider="fake")

        def chat(self, messages, tools, **kw):
            return self._next()

        def chat_stream(self, messages, tools, **kw):
            def _gen():
                yield from ()
                return self._next()

            return _gen()

    class _Reg(ToolRegistry):
        def execute(self, call):
            return ToolResult(
                status=ToolResultStatus.SUCCESS,
                content="ok",
                tool_call_id=call.id,
                tool_name=call.name,
                duration_ms=0.0,
            )

        def execute_many(self, calls):
            # 模拟缺结果：只返回 tc-a
            return [super().execute(calls[0])]

    reg = _Reg()
    reg.register(
        type(
            "RF",
            (),
            {"name": "read_file", "description": "t", "parameters": {"type": "object"}},
        )()
    )
    settings = Settings(
        llm_api_key="k",
        llm_base_url="https://x/v1",
        llm_model="m",
        data_dir=str(tmp_path / "data"),
        extract_enabled=False,
        summary_mode="off",
    )
    store = SessionStore(tmp_path / "sessions")
    engine = LoopEngine(
        llm_client=_Fake(),  # type: ignore[arg-type]
        registry=reg,  # type: ignore[arg-type]
        memory=None,  # type: ignore[arg-type]
        session=store,
        settings=settings,
    )
    result = engine.run_single("任务")
    assert result.final_answer
    sess = store.load(result.session_id)
    tool_msgs = [m for m in sess.messages if m.role == "tool"]
    # 对账: 声明 2 == 结果 1 + 取消 1
    assert len(tool_msgs) == 2
    cancelled = [m for m in tool_msgs if "执行中断" in m.content]
    assert len(cancelled) == 1
    assert cancelled[0].tool_call_id == "tc-b"
