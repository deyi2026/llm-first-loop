"""单元测试: LLM 客户端流式解析（T18 / 约束 C5 / LLMError 分类）.

mock httpx 流式响应，验证 tool_calls 聚合与异常分类。
"""

from __future__ import annotations

import contextlib
import json
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
    assert json.loads(tc.arguments) == {"path": "a.txt"}  # 原始 JSON 串，引擎层解析


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


def test_chat_no_auth_header_when_api_key_empty():
    """本地 provider（api_key 为空）不发 Authorization 头（修复 Illegal header value b'Bearer '）."""
    lines = [
        'data: {"choices": [{"delta": {"content": "ok"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        fake = _FakeStreamCtx(lines)
        client_cls.return_value.stream.return_value = fake
        _client(api_key="").chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    # 捕获 stream 调用参数，验证 headers 不含 Authorization
    _, kwargs = client_cls.return_value.stream.call_args
    headers = kwargs["headers"]
    assert "Authorization" not in headers, f"空 api_key 不应发 Authorization 头, 实际: {headers}"
    assert headers.get("Content-Type") == "application/json"


def test_chat_with_auth_header_when_api_key_present():
    """有 api_key 时正常发 Authorization: Bearer 头."""
    lines = [
        'data: {"choices": [{"delta": {"content": "ok"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        fake = _FakeStreamCtx(lines)
        client_cls.return_value.stream.return_value = fake
        _client(api_key="secret").chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    _, kwargs = client_cls.return_value.stream.call_args
    headers = kwargs["headers"]
    assert headers.get("Authorization") == "Bearer secret"


def test_local_provider_disables_thinking_in_payload():
    """本地 provider (api_key 空) 必须正确处理 thinking 字段.

    根因 (P1-FEISHU):
      1. qwen3 默认 enable_thinking=true → think 块耗尽 max_tokens → content 空 + truncated
      2. LM Studio 优先 OpenAI `thinking.type=enabled`，忽略 `chat_template_kwargs.enable_thinking=False`
         → 两者并存时仍输出 think 块（用户看到"你好 → 空回答 + 截断"）。

    修复: 本地 provider 跳过 OpenAI `thinking` 分支 + 仅发 chat_template_kwargs。
    """
    from unittest.mock import patch
    captured = {}

    def fake_stream(self, method, url, **kwargs):
        captured["json"] = kwargs.get("json", {})
        raise RuntimeError("STOP")

    from llm_loop.llm.client import LLMClient
    client = LLMClient(api_key="", base_url="http://localhost:1234/v1", model="m", timeout_s=5)
    with patch("httpx.Client.stream", fake_stream), contextlib.suppress(RuntimeError):
        list(client.chat_stream([{"role": "user", "content": "hi"}], tools=[]))

    p = captured.get("json", {})
    # 必须 1: chat_template_kwargs.enable_thinking=False
    assert "chat_template_kwargs" in p, f"本地 provider 缺 chat_template_kwargs, payload={p}"
    assert p["chat_template_kwargs"].get("enable_thinking") is False, \
        f"本地 provider 必须 enable_thinking=False, 实际={p['chat_template_kwargs']}"
    # 必须 2: 不应同时发 OpenAI thinking 字段（LM Studio 优先级冲突）
    assert "thinking" not in p, f"本地 provider 不应发 OpenAI thinking 字段（与 chat_template_kwargs 冲突）, payload={p}"


# ── 2026-08-15: max_tokens 显式装配（回答不再被模型默认 4096 截断）──

def test_chat_payload_max_tokens_sent():
    """显式配置 max_tokens → payload 携带（默认 4096 截断修复）."""
    lines = [
        'data: {"choices": [{"delta": {"content": "好"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        _client(max_tokens=8192).chat(messages=[{"role": "user", "content": "hi"}], tools=[])
        payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert payload.get("max_tokens") == 8192


def test_chat_payload_max_tokens_absent_when_none():
    """未配置 max_tokens（None）→ 不发字段（向后兼容）."""
    lines = [
        'data: {"choices": [{"delta": {"content": "好"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
        payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert "max_tokens" not in payload


def test_default_client_wired_with_settings_max_tokens(monkeypatch):
    """装配默认 client 携带 settings.llm_max_tokens（默认 8192，env 可调）."""
    from llm_loop.config import Settings, load_settings

    assert Settings.llm_max_tokens == 8192
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "http://t")
    monkeypatch.setenv("LLM_MODEL", "m")
    assert load_settings().llm_max_tokens == 8192
    monkeypatch.setenv("LLM_MAX_TOKENS", "16384")
    assert load_settings().llm_max_tokens == 16384


def test_factory_wires_max_tokens(monkeypatch):
    """factory 装配 default client 时传入 settings.llm_max_tokens."""
    from unittest import mock as _mock

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "http://t")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setenv("LLM_MAX_TOKENS", "8192")
    from llm_loop.config import load_settings

    settings = load_settings()
    with _mock.patch("llm_loop.factory.LLMClient") as client_cls:
        client_cls.return_value = _mock.MagicMock()
        from llm_loop.factory import build_engine

        build_engine(settings)
        kwargs = client_cls.call_args.kwargs
    assert kwargs.get("max_tokens") == 8192


# ── P3-5: 多协议（Anthropic / Google 原生协议） ──

def _stream_resp(lines, status=200, headers=None):
    resp = _FakeStreamCtx(lines, status_code=status)
    resp.headers = headers or {}
    return resp


def test_anthropic_payload_and_headers():
    """wire_protocol=anthropic：URL/头/payload 形状（system 拆分、tool_use/tool_result 转换）."""
    lines = [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":10,"output_tokens":0}}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"你好"}}',
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _stream_resp(lines)
        client = _client(wire_protocol="anthropic", api_key="k-an")
        it = client.chat_stream(
            messages=[
                {"role": "system", "content": "你是助手"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "tool_calls": [{"id": "t1", "name": "read_file", "arguments": {"p": "x"}}]},
                {"role": "tool", "tool_call_id": "t1", "content": "内容"},
            ],
            tools=[{"type": "function", "function": {"name": "read_file", "description": "d", "parameters": {"type": "object"}}}],
        )
        final = None
        while True:
            try:
                next(it)
            except StopIteration as e:
                final = e.value
                break
        url = client_cls.return_value.stream.call_args.args[1]
        assert url.endswith("/v1/messages")
        headers = client_cls.return_value.stream.call_args.kwargs["headers"]
        assert headers["x-api-key"] == "k-an"
        assert headers["anthropic-version"] == "2023-06-01"
        payload = client_cls.return_value.stream.call_args.kwargs["json"]
        assert payload["system"] == "你是助手"
        # 消息转换：tool_use / tool_result
        msgs = payload["messages"]
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"][0]["type"] == "tool_use"
        assert msgs[2]["role"] == "user"
        assert msgs[2]["content"][0]["type"] == "tool_result"
        assert final.content == "你好"
        assert final.prompt_tokens == 10


def test_anthropic_tool_use_aggregation():
    """Anthropic 工具声明聚合：tool_use 块 + input_json_delta 分片 → ToolCall."""
    lines = [
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"tu1","name":"read_file","input":{}}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"{\\"path\\": \\"a"}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":"\\"}"}}',
        'data: {"type":"content_block_stop","index":0}',
        'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"}}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _stream_resp(lines)
        it = _client(wire_protocol="anthropic").chat_stream(messages=[{"role": "user", "content": "x"}], tools=[])
        final = None
        while True:
            try:
                next(it)
            except StopIteration as e:
                final = e.value
                break
    assert len(final.tool_calls) == 1
    assert final.tool_calls[0].id == "tu1"
    assert final.tool_calls[0].name == "read_file"
    assert json.loads(final.tool_calls[0].arguments) == {"path": "a"}  # 原始 JSON 串，引擎层解析


def test_google_payload_and_stream():
    """wire_protocol=google：URL/头/payload（contents/systemInstruction/functionDeclarations）+ 流式解析."""
    lines = [
        'data: {"candidates":[{"content":{"parts":[{"text":"你好"}]},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":5,"candidatesTokenCount":2}}',
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _stream_resp(lines)
        client = _client(wire_protocol="google", api_key="k-g", base_url="https://generativelanguage.googleapis.com")
        it = client.chat_stream(
            messages=[{"role": "system", "content": "规则"}, {"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "web_fetch", "description": "d", "parameters": {"type": "object"}}}],
        )
        deltas = []
        while True:
            try:
                d = next(it)
                deltas.append(d.text)
            except StopIteration as e:
                final = e.value
                break
    url = client_cls.return_value.stream.call_args.args[1]
    assert ":streamGenerateContent?alt=sse" in url
    headers = client_cls.return_value.stream.call_args.kwargs["headers"]
    assert headers["x-goog-api-key"] == "k-g"
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert payload["systemInstruction"]["parts"][0]["text"] == "规则"
    assert payload["contents"][0]["parts"][0]["text"] == "hi"
    assert payload["tools"][0]["functionDeclarations"][0]["name"] == "web_fetch"
    assert "".join(deltas) == "你好"
    assert final.content == "你好"
    assert final.prompt_tokens == 5


def test_google_function_call_aggregation_and_truncation():
    """Google functionCall 聚合 + MAX_TOKENS → truncated."""
    lines = [
        'data: {"candidates":[{"content":{"parts":[{"functionCall":{"name":"read_file","args":{"p":"x"}}}]},"finishReason":"STOP"}]}',
        'data: {"candidates":[{"content":{"parts":[{"text":"部分"}]},"finishReason":"MAX_TOKENS"}]}',
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _stream_resp(lines)
        it = _client(wire_protocol="google").chat_stream(messages=[{"role": "user", "content": "x"}], tools=[])
        while True:
            try:
                next(it)
            except StopIteration as e:
                final = e.value
                break
    assert len(final.tool_calls) == 1
    assert final.tool_calls[0].name == "read_file"
    assert json.loads(final.tool_calls[0].arguments) == {"p": "x"}  # 原始 JSON 串
    assert final.truncated is True
    assert final.content == "部分"


def test_wire_protocol_default_openai_zero_regression():
    """默认 openai：URL/头与既有行为一致（零回归）."""
    lines = [
        'data: {"choices":[{"delta":{"content":"好"}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _stream_resp(lines)
        it = _client().chat_stream(messages=[{"role": "user", "content": "hi"}], tools=[])
        while True:
            try:
                next(it)
            except StopIteration as e:
                final = e.value
                break
    url = client_cls.return_value.stream.call_args.args[1]
    assert url.endswith("/chat/completions")
    assert final.content == "好"
