"""单元测试: LLM 客户端流式解析（T18 / 约束 C5 / LLMError 分类）.

mock httpx 流式响应，验证 tool_calls 聚合与异常分类。
"""

from __future__ import annotations

import contextlib
import json
from unittest import mock

import pytest

from llm_loop.llm.client import GuardRequestContext, LLMClient
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
    assert resp.finish_reason == "stop"


def test_chat_length_finish_reason_is_preserved_as_transport_fact():
    lines = [
        'data: {"choices": [{"delta": {"content": "PARTIAL"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "length"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.content == "PARTIAL"
    assert resp.truncated is True
    assert resp.finish_reason == "length"


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
    assert tc.arguments == {"path": "a.txt"}  # schemas finish 已归一为 dict（约束 C5）


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


def test_chat_reasoning_alias_aggregation():
    """mlx_lm dialect: delta.reasoning is normalized into reasoning_content."""
    lines = [
        'data: {"choices": [{"delta": {"reasoning": "思考过"}}]}',
        'data: {"choices": [{"delta": {"content": "你好", "reasoning": "程"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.reasoning_content == "思考过程"
    assert resp.content == "你好"


def test_chat_reasoning_details_cumulative_is_not_double_counted():
    """MiniMax-style cumulative reasoning_details: display dedup + raw replay preserved."""
    lines = [
        'data: {"choices": [{"delta": {"reasoning_details": [{"type": "reasoning.text", "text": "思考"}]}}]}',
        'data: {"choices": [{"delta": {"reasoning_details": [{"type": "reasoning.text", "text": "思考过程"}]}}]}',
        'data: {"choices": [{"delta": {"content": "答案"}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client(provider="minimax").chat(
            messages=[{"role": "user", "content": "hi"}], tools=[]
        )
    assert resp.reasoning_content == "思考过程"
    assert resp.content == "答案"
    assert resp.provider_replay == {
        "provider": "minimax",
        "fields": {
            "reasoning_details": [
                {"type": "reasoning.text", "text": "思考过程"}
            ]
        },
    }


def test_stream_state_hook_gets_opaque_reasoning_and_non_executable_tool_draft():
    """Hard-restart observer sees native state without changing normal ToolCall completion."""
    lines = [
        'data: {"choices": [{"delta": {"reasoning_details": [{"type": "reasoning.text", "text": "plan", "signature": "sig-1"}]}}]}',
        'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{\\"path\\":\\"py"}}]}}]}',
        'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "project.toml\\"}"}}]}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]}',
        "data: [DONE]",
    ]
    observed: list[dict] = []
    ctx = GuardRequestContext(stream_state_hook=observed.append)
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client(provider="minimax").chat(
            messages=[{"role": "user", "content": "read"}],
            tools=[{"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}],
            guard_context=ctx,
        )

    assert observed
    assert observed[0]["provider_replay"]["fields"]["reasoning_details"][0]["signature"] == "sig-1"
    draft_states = [s for s in observed if s.get("tool_call_drafts")]
    assert draft_states
    first_draft = draft_states[0]["tool_call_drafts"][0]
    assert first_draft["name"] == "read_file"
    assert first_draft["arguments_raw"] == '{"path":"py'
    assert resp.tool_calls[0].arguments == {"path": "pyproject.toml"}


def test_provider_replay_projects_only_to_matching_provider():
    """Opaque replay 不跨 provider 泄漏；匹配 provider 使用原生字段。"""
    lines = ['data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}', "data: [DONE]"]
    details = [{"type": "reasoning.text", "text": "raw"}]
    message = {
        "role": "assistant",
        "content": "old",
        "reasoning_content": "raw",
        "_provider_replay": {
            "provider": "minimax",
            "fields": {"reasoning_details": details},
        },
    }
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        _client(provider="minimax").chat(messages=[message], tools=[])
        minimax_payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert minimax_payload["messages"][0]["reasoning_details"] == details
    assert "reasoning_content" not in minimax_payload["messages"][0]
    assert "_provider_replay" not in minimax_payload["messages"][0]

    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        _client(provider="deepseek").chat(messages=[message], tools=[])
        other_payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert "reasoning_details" not in other_payload["messages"][0]
    assert "_provider_replay" not in other_payload["messages"][0]
    assert other_payload["messages"][0]["reasoning_content"] == "raw"


def test_provider_replay_survives_cross_provider_projection_and_returns_to_origin():
    """Projection is a view, never a mutation of durable provider replay state."""
    lines = ['data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}', "data: [DONE]"]
    details = [
        {
            "type": "reasoning.text",
            "text": "raw",
            "signature": "opaque-signature",
        }
    ]
    message = {
        "role": "assistant",
        "content": "old",
        "reasoning_content": "raw",
        "_provider_replay": {
            "provider": "minimax",
            "fields": {"reasoning_details": details},
        },
    }

    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        _client(provider="deepseek").chat(messages=[message], tools=[])
        deepseek_payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert "reasoning_details" not in deepseek_payload["messages"][0]
    assert message["_provider_replay"]["fields"]["reasoning_details"] == details

    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        _client(provider="minimax").chat(messages=[message], tools=[])
        minimax_payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert minimax_payload["messages"][0]["reasoning_details"] == details
    assert "reasoning_content" not in minimax_payload["messages"][0]


def test_reasoning_split_is_representation_contract_not_reasoning_control():
    """MiniMax M3 compatible format requests structured replay without enabling thinking."""
    lines = [
        'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        _client(
            provider="minimax",
            reasoning_split=True,
            reasoning_capable=True,
            reasoning_control="unknown",
            thinking_supported=False,
        ).chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert payload["reasoning_split"] is True
    assert "thinking" not in payload
    assert "reasoning_effort" not in payload


def test_reasoning_split_stays_legacy_for_old_tool_history_without_native_replay():
    """Do not switch a pre-P3 MiniMax tool chain to reasoning_details mid-history."""
    lines = [
        'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    messages = [
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "legacy-think",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "done"},
        {"role": "user", "content": "continue"},
    ]
    tools = [
        {
            "type": "function",
            "function": {"name": "read_file", "description": "x", "parameters": {"type": "object"}},
        }
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        _client(provider="minimax", reasoning_split=True).chat(messages=messages, tools=tools)
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert "reasoning_split" not in payload
    assert payload["messages"][0]["reasoning_content"] == "legacy-think"


def test_reasoning_split_uses_native_replay_when_tool_history_has_reasoning_details():
    lines = [
        'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    details = [{"type": "reasoning.text", "text": "native", "signature": "sig"}]
    messages = [
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "native",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
            "_provider_replay": {
                "provider": "minimax",
                "fields": {"reasoning_details": details},
            },
        },
        {"role": "tool", "tool_call_id": "c1", "content": "done"},
        {"role": "user", "content": "continue"},
    ]
    tools = [
        {
            "type": "function",
            "function": {"name": "read_file", "description": "x", "parameters": {"type": "object"}},
        }
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        _client(provider="minimax", reasoning_split=True).chat(messages=messages, tools=tools)
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert payload["reasoning_split"] is True
    assert payload["messages"][0]["reasoning_details"] == details
    assert "reasoning_content" not in payload["messages"][0]


def test_chat_reasoning_content_preferred_when_both_dialects_present():
    """Dual-key chunks are consumed once rather than double-counting reasoning."""
    lines = [
        'data: {"choices": [{"delta": {"reasoning_content": "canonical", "reasoning": "alias"}}]}',
        'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.reasoning_content == "canonical"
    assert resp.content == "ok"


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


def test_local_reasoning_mode_on_off_is_request_local(monkeypatch):
    """本地模型显式 on/off 必须落到 chat_template_kwargs，且不污染后续 auto。"""
    from llm_loop.core.run_context import current_reasoning_mode

    monkeypatch.delenv("LOCAL_ENABLE_THINKING", raising=False)
    payloads = []

    def fake_stream(self, method, url, **kwargs):
        payloads.append(kwargs.get("json", {}))
        return _FakeStreamCtx([
            'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}',
            "data: [DONE]",
        ])

    with mock.patch("httpx.Client.stream", fake_stream):
        c = _client(
            api_key="",
            base_url="http://127.0.0.1:8901/v1",
            thinking_supported=True,
        )
        token = current_reasoning_mode.set("on")
        try:
            c.chat(messages=[{"role": "user", "content": "on"}], tools=[])
        finally:
            current_reasoning_mode.reset(token)
        token = current_reasoning_mode.set("off")
        try:
            c.chat(messages=[{"role": "user", "content": "off"}], tools=[])
        finally:
            current_reasoning_mode.reset(token)
        c.chat(messages=[{"role": "user", "content": "auto"}], tools=[])

    assert payloads[0]["chat_template_kwargs"] == {"enable_thinking": True}
    assert payloads[1]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "chat_template_kwargs" not in payloads[2]


def test_remote_reasoning_mode_auto_off_on_is_request_local():
    """云端 auto 不覆盖 provider 默认；off/on 必须显式落到 wire。"""
    from llm_loop.core.run_context import current_reasoning_mode

    payloads = []

    def fake_stream(self, method, url, **kwargs):
        payloads.append(kwargs.get("json", {}))
        return _FakeStreamCtx([
            'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}',
            "data: [DONE]",
        ])

    with mock.patch("httpx.Client.stream", fake_stream):
        c = _client(provider="deepseek", thinking_supported=True)
        for mode in ("auto", "off", "on"):
            token = current_reasoning_mode.set(mode)
            try:
                c.chat(messages=[{"role": "user", "content": mode}], tools=[])
            finally:
                current_reasoning_mode.reset(token)

    assert "thinking" not in payloads[0]
    assert "reasoning_effort" not in payloads[0]
    assert payloads[1]["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payloads[1]
    assert payloads[2]["thinking"] == {"type": "enabled"}
    assert payloads[2]["reasoning_effort"] == "high"


def test_reasoning_capable_does_not_imply_control_protocol():
    """MiniMax 类模型可有 reasoning 能力，但 control=unknown 时 on/off 不应乱发 thinking 字段。"""
    from llm_loop.core.run_context import current_reasoning_mode

    payloads = []

    def fake_stream(self, method, url, **kwargs):
        payloads.append(kwargs.get("json", {}))
        return _FakeStreamCtx([
            'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}',
            "data: [DONE]",
        ])

    with mock.patch("httpx.Client.stream", fake_stream):
        c = _client(
            provider="minimax",
            thinking_supported=False,
            reasoning_capable=True,
            reasoning_control="unknown",
        )
        for mode in ("off", "on"):
            token = current_reasoning_mode.set(mode)
            try:
                state = c.reasoning_contract_state()
                c.chat(messages=[{"role": "user", "content": mode}], tools=[])
            finally:
                current_reasoning_mode.reset(token)
            assert state[1] is True  # capable
            assert state[2] == "unknown"
            assert state[3] is False  # no proven explicit control
            assert state[4] is None  # no request was actually applied

    assert all("thinking" not in payload for payload in payloads)
    assert all("chat_template_kwargs" not in payload for payload in payloads)


def test_always_on_effort_maps_off_to_low_without_sending_disabled():
    """GLM-5.3: off intent must not emit provider-invalid thinking.type=disabled."""
    from llm_loop.core.run_context import current_reasoning_mode

    payloads = []

    def fake_stream(self, method, url, **kwargs):
        payloads.append(kwargs.get("json", {}))
        return _FakeStreamCtx([
            'data: {"choices": [{"delta": {"reasoning_content": "r"}}]}',
            'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}',
            "data: [DONE]",
        ])

    with mock.patch("httpx.Client.stream", fake_stream):
        c = _client(
            provider="glm",
            thinking_supported=True,
            reasoning_capable=True,
            reasoning_control="always_on_effort",
            reasoning_effort="high",
        )
        for mode in ("auto", "off", "on"):
            token = current_reasoning_mode.set(mode)
            try:
                c.chat(messages=[{"role": "user", "content": mode}], tools=[])
            finally:
                current_reasoning_mode.reset(token)

    assert "thinking" not in payloads[0]
    assert "reasoning_effort" not in payloads[0]
    assert payloads[1]["thinking"] == {"type": "enabled"}
    assert payloads[1]["reasoning_effort"] == "low"
    assert payloads[2]["thinking"] == {"type": "enabled"}
    assert payloads[2]["reasoning_effort"] == "high"
    assert all(
        p.get("thinking") != {"type": "disabled"}
        for p in payloads
    )


def test_explicit_chat_template_contract_is_not_inferred_from_url():
    """chat_template 控制由模型 contract 决定，不依赖 localhost URL 猜测。"""
    from llm_loop.core.run_context import current_reasoning_mode

    payloads = []

    def fake_stream(self, method, url, **kwargs):
        payloads.append(kwargs.get("json", {}))
        return _FakeStreamCtx([
            'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}',
            "data: [DONE]",
        ])

    with mock.patch("httpx.Client.stream", fake_stream):
        c = _client(
            api_key="",
            base_url="http://127.0.0.1:8901/v1",
            thinking_supported=True,
            reasoning_capable=True,
            reasoning_control="chat_template",
        )
        token = current_reasoning_mode.set("on")
        try:
            c.chat(messages=[{"role": "user", "content": "on"}], tools=[])
        finally:
            current_reasoning_mode.reset(token)

    assert payloads[0]["chat_template_kwargs"] == {"enable_thinking": True}
    assert "thinking" not in payloads[0]


def test_openai_reasoning_tokens_usage_passthrough():
    """provider 给精确 reasoning_tokens 时如实透传，不做字符估算。"""
    lines = [
        'data: {"choices": [{"delta": {"reasoning": "想"}}]}',
        'data: {"choices": [{"delta": {"content": "答"}, "finish_reason": "stop"}]}',
        'data: {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 7, "completion_tokens_details": {"reasoning_tokens": 5}}}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.reasoning_content == "想"
    assert resp.reasoning_tokens == 5
    assert resp.completion_tokens == 7


def test_chat_payload_thinking_deepseek():
    """M20 THK-01: provider=deepseek → payload 含 thinking + reasoning_effort."""
    lines = ['data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}', "data: [DONE]"]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        c = _client(provider="deepseek")
        c.chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "high"


def test_chat_payload_reasoning_effort_context_override_is_request_local():
    """请求级 context override 优先于共享 client 默认，结束后不改实例属性。"""
    from llm_loop.core.run_context import current_reasoning_effort

    lines = ['data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}', "data: [DONE]"]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        c = _client(provider="deepseek", reasoning_effort="high")
        token = current_reasoning_effort.set("low")
        try:
            c.chat(messages=[{"role": "user", "content": "hi"}], tools=[])
        finally:
            current_reasoning_effort.reset(token)
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert payload["reasoning_effort"] == "low"
    assert c.reasoning_effort == "high"


def test_chat_payload_thinking_base_url_match():
    """M20 CFG-03: base_url 含 deepseek.com → 发送（不依赖 provider 字段）."""
    lines = ['data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}', "data: [DONE]"]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        c = LLMClient(api_key="k", base_url="https://api.deepseek.com/v1", model="m")
        c.chat(messages=[], tools=[])
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert "thinking" in payload


def test_chat_payload_thinking_non_deepseek_no():
    """M20 CFG-03: 非 DeepSeek（默认 fake.local）→ 无 thinking（零回归）."""
    lines = ['data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}', "data: [DONE]"]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        c = _client()  # fake.local
        c.chat(messages=[], tools=[])
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert "thinking" not in payload


def test_chat_payload_thinking_disabled():
    """M20 THK-01: thinking_mode=False → 无 thinking（VAL-01 对比组）."""
    lines = ['data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}', "data: [DONE]"]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        c = _client(provider="deepseek", thinking_mode=False)
        c.chat(messages=[], tools=[])
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert "thinking" not in payload


def test_chat_payload_tools_empty_thinking():
    """无工具时不进入 tool protocol；thinking 控制保持独立生效。"""
    lines = ['data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}', "data: [DONE]"]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        c = _client(provider="deepseek")  # thinking 默认开 + deepseek provider
        c.chat(messages=[{"role": "user", "content": "总结"}], tools=[])
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert payload["thinking"] == {"type": "enabled"}  # 思考参数保持发送（不降级）
    assert "tools" not in payload
    assert "tool_choice" not in payload


def test_chat_payload_nonempty_tools_enters_tool_protocol():
    """真正暴露工具时才发送 tools/tool_choice，避免 empty-tools 修复误伤工具调用。"""
    lines = ['data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}', "data: [DONE]"]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "lookup",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        c = _client(provider="deepseek")
        c.chat(messages=[{"role": "user", "content": "查一下"}], tools=tools)
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert payload["tools"] == tools
    assert payload["tool_choice"] == "auto"


def test_chat_payload_model_contract_can_omit_tool_choice():
    """Provider contract 可只发送 tools、依赖 provider 默认 auto，避免 thinking 兼容 400。"""
    lines = ['data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}', "data: [DONE]"]
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        c = _client(provider="deepseek", send_tool_choice=False)
        c.chat(messages=[{"role": "user", "content": "查一下"}], tools=tools)
    payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert payload["tools"] == tools
    assert "tool_choice" not in payload


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


def test_local_provider_disables_thinking_in_payload(monkeypatch):
    """本地 provider thinking 开关（2026-08-24 SWE 对照实验定论, 见 docs/swe_ab_report.md）.

    - 默认（LOCAL_ENABLE_THINKING 未设）: 本地【开启】thinking——A/B 实验证明
      关思考 0/4 漏掉第二修复点、开思考通过 F2P → 能力优先, 不发 enable_thinking=False。
    - 显式 LOCAL_ENABLE_THINKING=0: 发 chat_template_kwargs.enable_thinking=False
      （纯速度场景, 交互闲聊）。
    不变项: 本地不发 OpenAI `thinking` 字段（LM Studio 优先级冲突, P1-FEISHU）。
    """
    from unittest.mock import patch
    captured = {}

    def fake_stream(self, method, url, **kwargs):
        captured["json"] = kwargs.get("json", {})
        raise RuntimeError("STOP")

    from llm_loop.llm.client import LLMClient

    # 默认: 不开 enable_thinking=False（思考保持开启）
    monkeypatch.delenv("LOCAL_ENABLE_THINKING", raising=False)
    with patch("httpx.Client.stream", fake_stream), contextlib.suppress(RuntimeError):
        list(LLMClient(api_key="", base_url="http://localhost:1234/v1", model="m", timeout_s=5)
             .chat_stream([{"role": "user", "content": "hi"}], tools=[]))
    p = captured.get("json", {})
    assert "chat_template_kwargs" not in p, f"默认应保持思考开启, 实际={p.get('chat_template_kwargs')}"
    assert "thinking" not in p, f"本地 provider 不应发 OpenAI thinking 字段, payload={p}"

    # 显式 LOCAL_ENABLE_THINKING=0: 发 enable_thinking=False
    monkeypatch.setenv("LOCAL_ENABLE_THINKING", "0")
    captured.clear()
    with patch("httpx.Client.stream", fake_stream), contextlib.suppress(RuntimeError):
        list(LLMClient(api_key="", base_url="http://localhost:1234/v1", model="m", timeout_s=5)
             .chat_stream([{"role": "user", "content": "hi"}], tools=[]))
    p = captured.get("json", {})
    assert "chat_template_kwargs" in p, f"显式关闭时缺 chat_template_kwargs, payload={p}"
    assert p["chat_template_kwargs"].get("enable_thinking") is False, \
        f"LOCAL_ENABLE_THINKING=0 必须 enable_thinking=False, 实际={p['chat_template_kwargs']}"
    assert "thinking" not in p, f"本地 provider 不应发 OpenAI thinking 字段, payload={p}"


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



def test_chat_payload_explicit_generation_profile_sent():
    lines = [
        "data: {\"choices\": [{\"delta\": {\"content\": \"ok\"}}]}",
        "data: {\"choices\": [{\"delta\": {}, \"finish_reason\": \"stop\"}]}",
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        _client(temperature=0.0, top_p=1.0, top_k=0, min_p=0.0).chat(
            messages=[{"role": "user", "content": "hi"}], tools=[]
        )
        payload = client_cls.return_value.stream.call_args.kwargs["json"]
    assert payload["temperature"] == 0.0
    assert payload["top_p"] == 1.0
    assert payload["top_k"] == 0
    assert payload["min_p"] == 0.0

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
    """装配默认 client 携带 settings.llm_max_tokens（默认 16000，env 可调）."""
    from llm_loop.config import Settings, load_settings

    assert Settings.llm_max_tokens == 16000
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "http://t")
    monkeypatch.setenv("LLM_MODEL", "m")
    assert load_settings().llm_max_tokens == 16000
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
    assert final.tool_calls[0].arguments == {"path": "a"}  # schemas finish 已归一为 dict


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
    assert final.tool_calls[0].arguments == {"p": "x"}  # schemas finish 已归一为 dict
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


# ── M58: 前缀缓存命中 token 解析（DeepSeek prompt_cache_hit_tokens / Kimi cached_tokens / Anthropic cache_read）──

def test_chat_cache_hit_deepseek_field():
    """OpenAI 兼容（DeepSeek）：usage.prompt_cache_hit_tokens 解析入 LLMResponse."""
    lines = [
        'data: {"usage": {"prompt_tokens": 100, "completion_tokens": 5, "prompt_cache_hit_tokens": 70}}',
        'data: {"choices": [{"delta": {"content": "ok"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.prompt_tokens == 100
    assert resp.prompt_cache_hit_tokens == 70


def test_chat_cache_hit_kimi_cached_tokens():
    """OpenAI 兼容（Kimi 兜底）：usage.cached_tokens 解析入 LLMResponse."""
    lines = [
        'data: {"usage": {"prompt_tokens": 200, "completion_tokens": 8, "cached_tokens": 150}}',
        'data: {"choices": [{"delta": {"content": "ok"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.prompt_tokens == 200
    assert resp.prompt_cache_hit_tokens == 150


def test_chat_cache_hit_missing_zero():
    """usage 无缓存字段 → 0（不伪造）."""
    lines = [
        'data: {"usage": {"prompt_tokens": 50, "completion_tokens": 3}}',
        'data: {"choices": [{"delta": {"content": "ok"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.prompt_cache_hit_tokens == 0


def test_anthropic_cache_read_tokens():
    """Anthropic：usage.cache_read_input_tokens 解析入 LLMResponse."""
    lines = [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":300,"output_tokens":0,"cache_read_input_tokens":250}}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hi"}}',
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _stream_resp(lines)
        client = _client(wire_protocol="anthropic", api_key="k-an")
        it = client.chat_stream(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
        )
        final = None
        while True:
            try:
                next(it)
            except StopIteration as e:
                final = e.value
                break
    assert final.prompt_tokens == 300
    assert final.prompt_cache_hit_tokens == 250


def test_anthropic_orphan_tool_use_cleaned():
    """孤立 tool_use（声明无回执，LLM 失败/压缩裁剪场景）→ 清洗剔除，不 400.

    Anthropic 硬约束: tool_use 必须紧跟 tool_result。历史含孤立 tool_use 时
    转换层删除该块；整条仅剩孤立 tool_use 的 assistant 消息删除。
    """
    from llm_loop.llm.client import LLMClient
    out = LLMClient._to_anthropic_messages([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "tool_calls": [{"id": "t1", "name": "read_file", "arguments": {"p": "x"}}]},
        # t2 声明后无 tool 回执（孤立）
        {"role": "assistant", "content": "先看代码", "tool_calls": [{"id": "t2", "name": "grep", "arguments": {"q": "x"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "内容"},
        {"role": "user", "content": "继续"},
    ])
    # t2 孤立 → 该 assistant 消息的 tool_use 块被剔除，保留文本
    assert out[1]["content"][0]["type"] == "tool_use"  # t1 保留
    assert out[2]["content"] == [{"type": "text", "text": "先看代码"}]  # t2 剔除
    assert out[3]["content"][0]["type"] == "tool_result"
    assert out[4]["role"] == "user"


def test_anthropic_orphan_tool_result_skipped():
    """孤立 tool_result（无对应 tool_use）→ 跳过该 user 消息."""
    from llm_loop.llm.client import LLMClient
    out = LLMClient._to_anthropic_messages([
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "ghost", "content": "无主回执"},
        {"role": "user", "content": "继续"},
    ])
    roles = [m["role"] for m in out]
    assert roles == ["user", "user"]
    assert all("tool_result" not in json.dumps(m) for m in out)


def test_anthropic_all_orphan_tool_use_message_dropped():
    """assistant 消息仅含孤立 tool_use（无文本）→ 整条删除."""
    from llm_loop.llm.client import LLMClient
    out = LLMClient._to_anthropic_messages([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "tool_calls": [{"id": "t9", "name": "ls", "arguments": {}}]},
        {"role": "user", "content": "继续"},
    ])
    assert len(out) == 2
    assert out[0]["role"] == "user"
    assert out[1]["role"] == "user"


def test_anthropic_multi_tool_use_merged_tool_results():
    """2026-08-17 修复2: 一条 assistant 声明多个 tool_use + 连续 tool 回执
    → 回执必须合并为单条 user（多 tool_result 块），否则后续 tool_use 的
    tool_result 被前一条 user 隔开 → Anthropic 400 'without corresponding
    tool_result block immediately after'."""
    from llm_loop.llm.client import LLMClient

    msgs = [
        {"role": "user", "content": "并行查两个"},
        {"role": "assistant", "content": "\n\n",
         "tool_calls": [
             {"id": "A", "type": "function", "function": {"name": "f1", "arguments": "{}"}},
             {"id": "B", "type": "function", "function": {"name": "f2", "arguments": "{}"}},
         ]},
        {"role": "tool", "tool_call_id": "A", "content": "结果A"},
        {"role": "tool", "tool_call_id": "B", "content": "结果B"},
        {"role": "user", "content": "继续"},
    ]
    out = LLMClient._to_anthropic_messages(msgs)
    # 结构: user / assistant / user(合并回执) / user
    roles = [m["role"] for m in out]
    assert roles == ["user", "assistant", "user", "user"], roles
    # 合并回执单条 user 含 2 个 tool_result 块，顺序对应声明
    merged = out[2]["content"]
    assert [b["type"] for b in merged] == ["tool_result", "tool_result"]
    assert [b["tool_use_id"] for b in merged] == ["A", "B"]
    assert [b["content"] for b in merged] == ["结果A", "结果B"]
    # 后续 user 独立，不受影响
    assert out[3]["content"] == "继续"


def test_anthropic_single_tool_use_regression():
    """单 tool_use: 行为不变（单条 user 含单 tool_result）."""
    from llm_loop.llm.client import LLMClient

    msgs = [
        {"role": "assistant", "content": "查",
         "tool_calls": [{"id": "C", "type": "function", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "C", "content": "结果C"},
    ]
    out = LLMClient._to_anthropic_messages(msgs)
    assert out[-1]["role"] == "user"
    assert out[-1]["content"] == [
        {"type": "tool_result", "tool_use_id": "C", "content": "结果C"}
    ]


def test_anthropic_cache_control_localhost():
    """EVO-20260817 prompt caching: localhost base_url 自动启用 → system 数组 +
    tools 末条 cache_control（固化固定信息, 尾部追加 messages 只计费新增）."""
    lines = [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":10,"output_tokens":0}}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"好"}}',
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _stream_resp(lines)
        client = _client(wire_protocol="anthropic", api_key="k-an", base_url="http://localhost:1234/v1")
        it = client.chat_stream(
            messages=[{"role": "system", "content": "你是助手"}, {"role": "user", "content": "hi"}],
            tools=[
                {"type": "function", "function": {"name": "read_file", "description": "d", "parameters": {"type": "object"}}},
                {"type": "function", "function": {"name": "web_fetch", "description": "d", "parameters": {"type": "object"}}},
            ],
        )
        while True:
            try:
                next(it)
            except StopIteration:
                break
        payload = client_cls.return_value.stream.call_args.kwargs["json"]
        # system → 数组 + cache_control
        assert payload["system"] == [{"type": "text", "text": "你是助手", "cache_control": {"type": "ephemeral"}}]
        # tools 末条 cache_control（前缀固化）
        assert payload["tools"][0].get("cache_control") is None
        assert payload["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_anthropic_cache_control_remote_off():
    """远端 base_url 默认不启用 cache_control（零回归, 第三方端点兼容）."""
    lines = [
        'data: {"type":"message_start","message":{"usage":{"input_tokens":1,"output_tokens":0}}}',
        'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}',
        'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _stream_resp(lines)
        client = _client(wire_protocol="anthropic", api_key="k-an", base_url="https://api.example.com/v1")
        it = client.chat_stream(
            messages=[{"role": "system", "content": "你是助手"}, {"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "read_file", "description": "d", "parameters": {"type": "object"}}}],
        )
        while True:
            try:
                next(it)
            except StopIteration:
                break
        payload = client_cls.return_value.stream.call_args.kwargs["json"]
        assert payload["system"] == "你是助手"  # 字符串形态（无 cache_control）
        assert "cache_control" not in payload["tools"][0]


def test_anthropic_cache_control_env_override(monkeypatch):
    """env ANTHROPIC_CACHE_CONTROL=false 可关闭 localhost 缓存（fail-open 逃生口）."""
    monkeypatch.setenv("ANTHROPIC_CACHE_CONTROL", "false")
    client = _client(wire_protocol="anthropic", api_key="k", base_url="http://localhost:1234/v1")
    assert client._anthropic_cache_enabled() is False
    monkeypatch.setenv("ANTHROPIC_CACHE_CONTROL", "1")
    client2 = _client(wire_protocol="anthropic", api_key="k", base_url="https://remote.example.com/v1")
    assert client2._anthropic_cache_enabled() is True


# ── EVO-20260824: 大上下文流式断连重试（deepseek 150K+ 字符偶发 peer closed connection）──
def test_chat_disconnect_retry_no_output():
    """断连发生在「尚无输出已产出」时 → 同请求自动重试 1 次成功（UI 无重复）."""
    import httpx

    from llm_loop.llm.errors import LLMNetworkError

    lines = [
        'data: {"choices": [{"delta": {"content": "你好"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    good = _FakeStreamCtx(lines)
    state = {"called": False}

    def _side_effect(*_a, **_k):
        if not state["called"]:
            state["called"] = True
            raise httpx.RemoteProtocolError(
                "peer closed connection without sending complete message body (incomplete chunked read)"
            )
        return good

    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.side_effect = _side_effect
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.content == "你好"
    assert client_cls.return_value.stream.call_count == 2
    assert not isinstance(resp, LLMNetworkError)


def test_chat_disconnect_no_retry_after_output():
    """已有输出已产出后断连 → 不重试（防 UI/工具重复）→ LLMNetworkError."""
    import httpx

    from llm_loop.llm.errors import LLMNetworkError

    class _DisconnectAfterOne(_FakeStreamCtx):
        def __init__(self) -> None:
            super().__init__([])

        def iter_lines(self):
            yield 'data: {"choices": [{"delta": {"content": "部分"}}]}'
            raise httpx.RemoteProtocolError(
                "peer closed connection without sending complete message body (incomplete chunked read)"
            )

    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _DisconnectAfterOne()
        with pytest.raises(LLMNetworkError):
            _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    # 只调用一次（有输出已产出 → 不重试）
    assert client_cls.return_value.stream.call_count == 1


def test_chat_disconnect_retry_disabled(monkeypatch):
    """env LLM_RETRY_DISCONNECT=0 关闭重试 → 断连直接如实报错."""
    import httpx

    from llm_loop.llm.errors import LLMNetworkError

    monkeypatch.setenv("LLM_RETRY_DISCONNECT", "0")
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.side_effect = httpx.RemoteProtocolError("peer closed connection")
        with pytest.raises(LLMNetworkError):
            _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert client_cls.return_value.stream.call_count == 1


def test_chat_disconnect_retry_tool_delta_no_retry():
    """工具 delta 已产出后断连 → 不重试（防工具重复执行）→ LLMNetworkError."""
    import httpx

    from llm_loop.llm.errors import LLMNetworkError

    class _DisconnectAfterTool(_FakeStreamCtx):
        def __init__(self) -> None:
            super().__init__([])

        def iter_lines(self):
            yield (
                'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_9", '
                '"type": "function", "function": {"name": "read_file", "arguments": "{}"}}]}}]}'
            )
            raise httpx.RemoteProtocolError("peer closed connection")

    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _DisconnectAfterTool()
        with pytest.raises(LLMNetworkError):
            _client().chat(messages=[{"role": "user", "content": "读文件"}], tools=[])
    assert client_cls.return_value.stream.call_count == 1


# ── 2026-08-24 本地直连忽略系统代理（trust_env）──
# httpx 默认 trust_env=True 经 urllib 读取 macOS 系统代理（Surge 等把 127.0.0.1:6152
# 设为系统代理）→ 回环 LLM 请求被转给代理 → 503 Connection Closed → "本地模型出错"。
# 本地 base_url → trust_env=False 直连; 远程保持默认; env LLM_TRUST_ENV 显式覆盖。


def test_local_client_trust_env_false(monkeypatch):
    """本地 base_url → trust_env=False（回环直连, 忽略系统代理）."""
    monkeypatch.delenv("LLM_TRUST_ENV", raising=False)
    c = _client(base_url="http://127.0.0.1:1234/v1")
    assert c._client.trust_env is False


def test_remote_client_trust_env_default(monkeypatch):
    """远程 base_url → trust_env=True（保持系统代理能力, 零回归）."""
    monkeypatch.delenv("LLM_TRUST_ENV", raising=False)
    c = _client(base_url="https://api.deepseek.com/v1")
    assert c._client.trust_env is True


def test_llm_trust_env_override(monkeypatch):
    """env LLM_TRUST_ENV 显式覆盖（本地可启用代理, 远程可禁用）."""
    monkeypatch.setenv("LLM_TRUST_ENV", "1")
    c = _client(base_url="http://127.0.0.1:1234/v1")
    assert c._client.trust_env is True
    monkeypatch.setenv("LLM_TRUST_ENV", "0")
    c2 = _client(base_url="https://api.deepseek.com/v1")
    assert c2._client.trust_env is False


def test_chat_think_tags_strip_markers_exactly():
    """M3 content-think: 完整标签应只把内部内容归为 reasoning，不泄漏标签。"""
    lines = [
        'data: {"choices": [{"delta": {"content": "前缀<think>秘密推理</think>答案"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.content == "前缀答案"
    assert resp.reasoning_content == "秘密推理"


def test_chat_think_tags_can_split_across_sse_chunks():
    """opening/closing 标签任意跨 delta 分片时也不能泄漏进正文或 reasoning。"""
    lines = [
        'data: {"choices": [{"delta": {"content": "前缀<th"}}]}',
        'data: {"choices": [{"delta": {"content": "ink>秘密推"}}]}',
        'data: {"choices": [{"delta": {"content": "理</th"}}]}',
        'data: {"choices": [{"delta": {"content": "ink>答案"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ]
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.return_value = _FakeStreamCtx(lines)
        resp = _client().chat(messages=[{"role": "user", "content": "hi"}], tools=[])
    assert resp.content == "前缀答案"
    assert resp.reasoning_content == "秘密推理"


def test_unclosed_think_does_not_poison_next_request():
    """未闭合标签按字面正文回吐，且下一请求仍从干净 parser 状态开始。"""
    first = _FakeStreamCtx([
        'data: {"choices": [{"delta": {"content": "<think>未闭合推理"}}]}',
        "data: [DONE]",
    ])
    second = _FakeStreamCtx([
        'data: {"choices": [{"delta": {"content": "下一轮正文"}}]}',
        'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}',
        "data: [DONE]",
    ])
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.side_effect = [first, second]
        c = _client()
        first_resp = c.chat(messages=[{"role": "user", "content": "first"}], tools=[])
        resp = c.chat(messages=[{"role": "user", "content": "second"}], tools=[])
    assert first_resp.content == "<think>未闭合推理"
    assert first_resp.reasoning_content is None
    assert resp.content == "下一轮正文"
    assert resp.reasoning_content is None


def test_concurrent_streams_on_same_client_have_isolated_think_state():
    """共享 provider client 的并发 session 不得共享 think parser 状态。"""
    first = _FakeStreamCtx([
        'data: {"choices": [{"delta": {"content": "<think>A"}}]}',
        # 第二个 reasoning delta 让旧实现先把 self._in_think=True 写回共享 client，
        # 再把 generator 停在下一次 yield；此时启动 g2 可稳定暴露跨会话污染。
        'data: {"choices": [{"delta": {"content": "B"}}]}',
        'data: {"choices": [{"delta": {"content": "</think>done-a"}}]}',
        "data: [DONE]",
    ])
    second = _FakeStreamCtx([
        'data: {"choices": [{"delta": {"content": "visible-b"}}]}',
        "data: [DONE]",
    ])
    with mock.patch("httpx.Client") as client_cls:
        client_cls.return_value.stream.side_effect = [first, second]
        c = _client()
        g1 = c.chat_stream([{"role": "user", "content": "a"}], [])
        # 为保证未闭合字面标签不被误分类，reasoning 在 close tag 到达前不提前吐出。
        d1 = next(g1)
        assert d1.reasoning == "AB"
        g2 = c.chat_stream([{"role": "user", "content": "b"}], [])
        d2 = next(g2)
        assert d2.text == "visible-b"
        d1b = next(g1)
        assert d1b.text == "done-a"
        g1.close()
        g2.close()


def test_interruption_replay_marker_is_not_projected_across_human_boundary():
    """Captured native replay remains durable recovery evidence, not new-turn action state."""
    from llm_loop.core.message import Message, MessageSource
    from llm_loop.core.recent_continuity import apply_recent_continuity_suffix

    replay = {
        "provider": "minimax",
        "fields": {
            "reasoning_details": [
                {"type": "reasoning.text", "text": "plan", "signature": "sig-1"}
            ]
        },
    }
    current = Message(role="user", content="continue", source=MessageSource.USER)
    resumed, _ = apply_recent_continuity_suffix(
        [{"role": "system", "content": "SYS"}, current.to_llm_dict()],
        session_messages=[
            Message(role="user", content="inspect", source=MessageSource.USER),
            current,
        ],
        current_turn_ref=1,
        interruption_resume={
            "source": "open_stream_checkpoint",
            "text_tail": "PARTIAL",
            "reasoning_tail": "plan",
            "provider_replay": replay,
        },
    )
    assert resumed[-2] == {"role": "assistant", "content": "PARTIAL"}

    minimax = _client(provider="minimax")._project_provider_replay(resumed)  # noqa: SLF001
    foreign = _client(provider="deepseek")._project_provider_replay(resumed)  # noqa: SLF001

    assert "reasoning_details" not in minimax[-2]
    assert "_provider_replay" not in minimax[-2]
    assert "reasoning_content" not in minimax[-2]
    assert "reasoning_details" not in foreign[-2]
    assert "_provider_replay" not in foreign[-2]
    assert "reasoning_content" not in foreign[-2]


def test_chat_template_reasoning_effort_uses_explicit_model_mapping() -> None:
    from llm_loop.core.run_context import current_reasoning_effort, current_reasoning_mode

    payloads = []

    def fake_stream(self, method, url, **kwargs):
        payloads.append(kwargs.get("json", {}))
        return _FakeStreamCtx([
            'data: {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]}',
            "data: [DONE]",
        ])

    with mock.patch("httpx.Client.stream", fake_stream):
        c = _client(
            api_key="",
            base_url="http://127.0.0.1:8901/v1",
            thinking_supported=True,
            reasoning_capable=True,
            reasoning_control="chat_template",
            reasoning_effort="high",
            reasoning_effort_map={"high": "medium", "max": "xhigh"},
        )
        mode_token = current_reasoning_mode.set("on")
        effort_token = current_reasoning_effort.set("high")
        try:
            c.chat(messages=[{"role": "user", "content": "high"}], tools=[])
        finally:
            current_reasoning_effort.reset(effort_token)
            current_reasoning_mode.reset(mode_token)
        mode_token = current_reasoning_mode.set("on")
        effort_token = current_reasoning_effort.set("max")
        try:
            c.chat(messages=[{"role": "user", "content": "max"}], tools=[])
        finally:
            current_reasoning_effort.reset(effort_token)
            current_reasoning_mode.reset(mode_token)
        mode_token = current_reasoning_mode.set("off")
        try:
            c.chat(messages=[{"role": "user", "content": "off"}], tools=[])
        finally:
            current_reasoning_mode.reset(mode_token)

    assert payloads[0]["chat_template_kwargs"] == {
        "enable_thinking": True,
        "reasoning_effort": "medium",
    }
    assert payloads[1]["chat_template_kwargs"] == {
        "enable_thinking": True,
        "reasoning_effort": "xhigh",
    }
    assert payloads[2]["chat_template_kwargs"] == {"enable_thinking": False}
