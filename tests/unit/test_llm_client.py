"""单元测试: LLM 客户端流式解析（T18 / 约束 C5 / LLMError 分类）.

mock httpx 流式响应，验证 tool_calls 聚合与异常分类。
"""

from __future__ import annotations

from unittest import mock

import pytest

from llm_loop.llm.client import LLMClient
from llm_loop.llm.errors import LLMHTTPError, LLMTimeoutError


def _client(**overrides) -> LLMClient:
    kwargs = dict(api_key="k", base_url="https://fake.local/v1", model="m", timeout_s=10.0)
    kwargs.update(overrides)
    return LLMClient(**kwargs)


class _FakeStreamCtx:
    """模拟 httpx.Client.stream 上下文（提供 iter_lines / read）."""

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


def test_chat_content_only():
    """流式仅 content → 最终回答."""
    lines = [
        'data: {"choices": [{"delta": {"content": "你好"}}]}',
        'data: {"choices": [{"delta": {"content": "世界"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.content == "你好世界"
    assert resp.tool_calls == []


def test_chat_tool_calls_aggregation():
    """流式 tool_calls 分片聚合（约束 C5）."""
    lines = [
        'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_9", "type": "function", "function": {"name": "read_file", "arguments": "{\\"path\\":\\"a"}}]}}]}',
        'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ".txt\\"}"}}]}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "读文件"}], tools=[])
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc.id == "call_9"
    assert tc.name == "read_file"
    assert tc.arguments == {"path": "a.txt"}


def test_chat_http_400():
    """HTTP 400 → LLMHTTPError（含 body）."""
    stream = _FakeStreamCtx([], status_code=400, body=b'{"error": "bad"}')
    stream.reason_phrase = "Bad Request"
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = stream
        with pytest.raises(LLMHTTPError) as exc_info:
            _client().chat(messages=[], tools=[])
    assert exc_info.value.status_code == 400
    assert "bad" in exc_info.value.body


def test_chat_timeout():
    """超时 → LLMTimeoutError."""
    import httpx

    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.side_effect = httpx.TimeoutException("t")
        with pytest.raises(LLMTimeoutError):
            _client().chat(messages=[], tools=[])


def test_chat_reasoning_content_aggregation():
    """M20 THK-02: reasoning_content 分片拼接（与 content/tool_calls 并行互不干扰）."""
    lines = [
        'data: {"choices": [{"delta": {"reasoning_content": "思考过"}}]}',
        'data: {"choices": [{"delta": {"content": "你好", "reasoning_content": "程"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.reasoning_content == "思考过程"
    assert resp.content == "你好"


def test_chat_reasoning_content_missing():
    """M20 THK-03: 全部 chunk 无 reasoning_content → None（缺失态兼容）."""
    lines = [
        'data: {"choices": [{"delta": {"content": "你好"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.reasoning_content is None
    assert resp.content == "你好"


def test_chat_payload_thinking_deepseek():
    """M20 THK-01: provider=deepseek → payload 含 thinking + reasoning_effort."""
    lines = ['data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}', "data: [DONE]"]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        c = _client(provider="deepseek")
        c.chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"


def test_chat_payload_thinking_base_url_match():
    """M20 CFG-03: base_url 含 deepseek.com → 发送（不依赖 provider 字段）."""
    lines = ['data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}', "data: [DONE]"]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        c = LLMClient(api_key="k", base_url="https://api.deepseek.com/v1", model="m")
        c.chat(messages=[], tools=[])
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert "thinking" in payload


def test_chat_payload_thinking_non_deepseek_no():
    """M20 CFG-03: 非 DeepSeek（默认 fake.local）→ 无 thinking（零回归）."""
    lines = ['data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}', "data: [DONE]"]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        c = _client()  # fake.local
        c.chat(messages=[], tools=[])
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert "thinking" not in payload


def test_chat_payload_thinking_disabled():
    """M20 THK-01: thinking_mode=False → 无 thinking（VAL-01 对比组）."""
    lines = ['data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}', "data: [DONE]"]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        c = _client(provider="deepseek", thinking_mode=False)
        c.chat(messages=[], tools=[])
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert "thinking" not in payload


def test_chat_payload_tools_empty_thinking():
    """M21 AUX-03: tools=[] + thinking enabled → payload 含思考参数且 tools 为空数组（协议边界锁定）."""
    lines = ['data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}', "data: [DONE]"]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        c = _client(provider="deepseek")  # thinking 默认开 + deepseek provider
        c.chat(messages=[{"role": "user", "content": "总结"}], tools=[])
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert payload["thinking"] == {"type": "enabled"}  # 思考参数保持发送（不降级）
    assert payload["tools"] == []  # 空数组原样携带（FIX-02 未触发时的基线断言）
