"""流式等价测试（spec 5.2 规则 4 / design §2.4.2 / tasks 2.6）.

断言:
1. client.chat_stream 的 delta 拼接 == 同步 chat 的 content
2. client.chat（包装后）返回字段一致（content/tool_calls/usage）
3. engine.run_stream 的 delta 拼接 == run 的 final_answer（等价性不变量）
4. engine.run_stream 与 run 的 LoopResult final_answer 一致
"""

from __future__ import annotations

from unittest import mock

from llm_loop.llm.client import LLMClient, LLMResponse, StreamDelta


class _FakeStreamCtx:
    """模拟 httpx.Client.stream 上下文（iter_lines / read）."""

    def __init__(self, lines: list[str], status_code: int = 200, body: bytes = b"") -> None:
        self._lines = lines
        self.status_code = status_code
        self.reason_phrase = "OK"
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_lines(self):
        yield from self._lines

    def read(self) -> bytes:
        return self._body


class StreamingFakeLLM:
    """支持 chat_stream 的 FakeLLM（engine 流式等价测试用）."""

    def __init__(self, content: str, tool_calls=None, reasoning_content=None) -> None:
        self._content = content
        self._tool_calls = tool_calls or []
        self._reasoning = reasoning_content
        self.calls: list[dict] = []
        self.model = "fake-model"
        self.timeout_s = 120.0
        self.thinking_mode = True
        self.reasoning_effort = "high"
        self.thinking_supported = True

    def chat(self, messages, tools, *, timeout_s=None, model=None) -> LLMResponse:
        self.calls.append({"messages": messages, "model": model})
        return LLMResponse(
            content=self._content,
            tool_calls=self._tool_calls,
            provider="fake",
            reasoning_content=self._reasoning,
        )

    def chat_stream(self, messages, tools, *, timeout_s=None, model=None):
        self.calls.append({"messages": messages, "model": model})
        for ch in self._content:
            yield StreamDelta(text=ch)
        return LLMResponse(
            content=self._content,
            tool_calls=self._tool_calls,
            provider="fake",
            reasoning_content=self._reasoning,
        )


def _consume(gen):
    out = []
    while True:
        try:
            out.append(next(gen))
        except StopIteration as exc:
            return out, exc.value


def _client(**overrides) -> LLMClient:
    kwargs = dict(api_key="k", base_url="https://fake.local/v1", model="m", timeout_s=10.0)
    kwargs.update(overrides)
    return LLMClient(**kwargs)


class TestClientStreamEquivalence:
    def test_chat_stream_deltas_equal_chat_content(self):
        lines = [
            'data: {"choices": [{"delta": {"content": "你好"}}]}',
            'data: {"choices": [{"delta": {"content": "世界"}}]}',
            'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
            "data: [DONE]",
        ]
        with mock.patch("httpx.Client") as client_cls:
            client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
            deltas, resp = _consume(
                _client().chat_stream(messages=[{"role": "user", "content": "hi"}], tools=[])
            )
        assert "".join(d.text for d in deltas) == "你好世界"
        assert resp.content == "你好世界"

    def test_chat_wrapper_fields_unchanged(self):
        lines = [
            'data: {"choices": [{"delta": {"content": "答案"}}]}',
            'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
            'data: {"usage": {"prompt_tokens": 5, "completion_tokens": 3}}',
            "data: [DONE]",
        ]
        with mock.patch("httpx.Client") as client_cls:
            client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
            resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
        assert resp.content == "答案"
        assert resp.tool_calls == []
        assert resp.prompt_tokens == 5
        assert resp.completion_tokens == 3


class TestEngineStreamEquivalence:
    def test_run_stream_deltas_equal_final_answer(self, build_test_engine):
        engine, _ = build_test_engine([])
        engine.llm_pool.default_client = StreamingFakeLLM("你好世界")

        deltas, stream_result = _consume(engine.run_stream("sid-stream", "hi"))
        assert "".join(d.text for d in deltas) == "你好世界"
        assert stream_result.final_answer == "你好世界"

        result = engine.run("sid-sync", "hi")
        assert result.final_answer == "你好世界"
        assert stream_result.rounds == result.rounds
