"""P5: exact provider-visible packet integrity at the physical transport boundary.

These tests deliberately patch the already-constructed ``LLMClient._client.stream``
method.  Patching ``httpx.Client`` after construction does not observe the transport
used by the instance and can create a false-green qualification.
"""

from __future__ import annotations

import dataclasses
import json
from copy import deepcopy
from unittest import mock

import httpx
import pytest

from llm_loop.core.message import Message, MessageSource
from llm_loop.llm.client import GuardRequestContext, LLMClient
from llm_loop.llm.errors import LLMHTTPError, LLMNetworkError, LLMProjectionError
from llm_loop.llm.pool import ModelClientPool
from llm_loop.llm.providers import load_registry
from llm_loop.runtime.causality import effective_generation_contract
from tests.unit.test_llm_client import _client, _FakeStreamCtx


def _canonical_messages() -> list[dict]:
    """Production-shaped history: engine persists OpenAI-canonical nested calls."""
    return [
        {"role": "system", "content": "SYS"},
        {
            "role": "user",
            "content": "DELEGATED",
            "_active_run_ingress_ref": "7",
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-a",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": json.dumps({"path": "a.txt"}),
                    },
                },
                {
                    "id": "call-b",
                    "type": "function",
                    "function": {
                        "name": "search_files",
                        "arguments": json.dumps({"pattern": "needle"}),
                    },
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call-a", "name": "read_file", "content": "A"},
        {
            "role": "tool",
            "tool_call_id": "call-b",
            "name": "search_files",
            "content": "B",
        },
    ]


def _guard() -> GuardRequestContext:
    return GuardRequestContext(
        session_id="p5-wire",
        active_run_ingress_ref="7",
        active_run_ingress_kind="delegated",
    )


def _capture_send(client: LLMClient, lines: list[str]) -> dict:
    stream = mock.Mock(return_value=_FakeStreamCtx(lines))
    client._client.stream = stream  # type: ignore[method-assign]  # noqa: SLF001
    client.chat(messages=_canonical_messages(), tools=[], guard_context=_guard())
    return stream.call_args.kwargs["json"]


def test_openai_actual_send_keeps_exact_ingress_and_atomic_tool_group() -> None:
    payload = _capture_send(
        _client(provider="glm"),
        [
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ],
    )

    assert "_active_run_ingress_ref" not in json.dumps(payload)
    messages = payload["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool", "tool"]
    assert messages[1]["content"] == "DELEGATED"
    assert [tc["id"] for tc in messages[2]["tool_calls"]] == ["call-a", "call-b"]
    assert [m["tool_call_id"] for m in messages[3:]] == ["call-a", "call-b"]


def test_openai_actual_send_canonicalizes_legacy_flat_tool_call() -> None:
    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "CURRENT", "_active_run_ingress_ref": "7"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "legacy-1",
                    "name": "read_file",
                    "arguments": {"path": "legacy.txt"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "legacy-1", "content": "OK"},
    ]
    client = _client(provider="glm")
    stream = mock.Mock(
        return_value=_FakeStreamCtx(
            [
                'data: {"choices":[{"delta":{"content":"ok"}}]}',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                "data: [DONE]",
            ]
        )
    )
    client._client.stream = stream  # type: ignore[method-assign]  # noqa: SLF001
    client.chat(messages=messages, tools=[], guard_context=_guard())

    sent = stream.call_args.kwargs["json"]["messages"]
    tool_call = sent[2]["tool_calls"][0]
    assert tool_call == {
        "id": "legacy-1",
        "type": "function",
        "function": {
            "name": "read_file",
            "arguments": json.dumps({"path": "legacy.txt"}, ensure_ascii=False),
        },
    }


def test_anthropic_actual_send_projects_canonical_tool_names_and_arguments() -> None:
    payload = _capture_send(
        _client(provider="anthropic", wire_protocol="anthropic"),
        [
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"ok"}}',
            'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}',
            "data: [DONE]",
        ],
    )

    assert "_active_run_ingress_ref" not in json.dumps(payload)
    messages = payload["messages"]
    assert messages[0] == {"role": "user", "content": "DELEGATED"}
    uses = messages[1]["content"]
    assert [(b["id"], b["name"], b["input"]) for b in uses] == [
        ("call-a", "read_file", {"path": "a.txt"}),
        ("call-b", "search_files", {"pattern": "needle"}),
    ]
    results = messages[2]["content"]
    assert [(b["tool_use_id"], b["content"]) for b in results] == [
        ("call-a", "A"),
        ("call-b", "B"),
    ]


def test_google_actual_send_projects_canonical_tool_names_and_arguments() -> None:
    payload = _capture_send(
        _client(
            provider="google",
            wire_protocol="google",
            base_url="https://generativelanguage.googleapis.com",
        ),
        [
            'data: {"candidates":[{"content":{"parts":[{"text":"ok"}]},"finishReason":"STOP"}]}',
        ],
    )

    assert "_active_run_ingress_ref" not in json.dumps(payload)
    contents = payload["contents"]
    assert contents[0] == {"role": "user", "parts": [{"text": "DELEGATED"}]}
    calls = contents[1]["parts"]
    assert [part["functionCall"] for part in calls] == [
        {"name": "read_file", "args": {"path": "a.txt"}},
        {"name": "search_files", "args": {"pattern": "needle"}},
    ]
    responses = [item["parts"][0]["functionResponse"] for item in contents[2:]]
    assert responses == [
        {"name": "read_file", "response": {"result": "A"}},
        {"name": "search_files", "response": {"result": "B"}},
    ]


def test_cross_provider_replay_scope_mismatch_is_absent_from_actual_send() -> None:
    source = _client(provider="minimax", model="MiniMax-M3", reasoning_split=True)
    replay = {
        "provider": source.provider,
        "model": source.model,
        "generation_contract": effective_generation_contract(source),
        "fields": {
            "reasoning_details": [
                {"type": "reasoning.text", "text": "native", "signature": "source-only"}
            ]
        },
    }
    messages = [
        {"role": "system", "content": "SYS"},
        {
            "role": "assistant",
            "content": "VISIBLE",
            "reasoning_content": "normalized-visible-reasoning",
            "_provider_replay": replay,
        },
        {"role": "user", "content": "CURRENT", "_active_run_ingress_ref": "7"},
    ]
    target = _client(provider="deepseek", model="MiniMax-M3", reasoning_split=True)
    stream = mock.Mock(
        return_value=_FakeStreamCtx(
            [
                'data: {"choices":[{"delta":{"content":"ok"}}]}',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                "data: [DONE]",
            ]
        )
    )
    target._client.stream = stream  # type: ignore[method-assign]  # noqa: SLF001
    target.chat(messages=messages, tools=[], guard_context=_guard())

    payload = stream.call_args.kwargs["json"]
    wire = json.dumps(payload)
    assert "_provider_replay" not in wire
    assert "_active_run_ingress_ref" not in wire
    assert "source-only" not in wire
    assert payload["messages"][1]["reasoning_content"] == "normalized-visible-reasoning"


@pytest.mark.parametrize("wire_protocol", ["anthropic", "google"])
def test_native_protocol_invalid_canonical_arguments_fail_before_transport(
    wire_protocol: str,
) -> None:
    messages = _canonical_messages()
    messages[2]["tool_calls"][0]["function"]["arguments"] = "[1, 2, 3]"
    client = _client(
        provider=wire_protocol,
        wire_protocol=wire_protocol,
        base_url=(
            "https://generativelanguage.googleapis.com"
            if wire_protocol == "google"
            else "https://fake.local/v1"
        ),
    )
    stream = mock.Mock(return_value=_FakeStreamCtx([]))
    client._client.stream = stream  # type: ignore[method-assign]  # noqa: SLF001

    with pytest.raises(LLMProjectionError) as exc_info:
        client.chat(messages=messages, tools=[], guard_context=_guard())

    assert "tool_call_arguments_not_object:call-a" in exc_info.value.violations
    assert stream.call_count == 0, "invalid provider projection must fail before transport"


@pytest.mark.parametrize("wire_protocol", ["anthropic", "google"])
def test_native_protocol_invalid_json_arguments_fail_before_transport(
    wire_protocol: str,
) -> None:
    messages = _canonical_messages()
    messages[2]["tool_calls"][0]["function"]["arguments"] = "{broken"
    client = _client(
        provider=wire_protocol,
        wire_protocol=wire_protocol,
        base_url=(
            "https://generativelanguage.googleapis.com"
            if wire_protocol == "google"
            else "https://fake.local/v1"
        ),
    )
    stream = mock.Mock(return_value=_FakeStreamCtx([]))
    client._client.stream = stream  # type: ignore[method-assign]  # noqa: SLF001

    with pytest.raises(LLMProjectionError) as exc_info:
        client.chat(messages=messages, tools=[], guard_context=_guard())

    assert "tool_call_arguments_invalid_json:call-a" in exc_info.value.violations
    assert stream.call_count == 0, "invalid provider projection must fail before transport"


@pytest.mark.parametrize(
    ("mutation", "expected_violation"),
    [
        ("missing_name", "tool_call_name_missing:call-a"),
        ("invalid_json", "tool_call_arguments_invalid_json:call-a"),
        ("non_object", "tool_call_arguments_not_object:call-a"),
    ],
)
def test_openai_invalid_canonical_tool_call_fails_before_transport(
    mutation: str, expected_violation: str
) -> None:
    messages = _canonical_messages()
    function = messages[2]["tool_calls"][0]["function"]
    if mutation == "missing_name":
        function["name"] = ""
    elif mutation == "invalid_json":
        function["arguments"] = "{broken"
    else:
        function["arguments"] = "[1, 2, 3]"
    client = _client(provider="glm")
    stream = mock.Mock(return_value=_FakeStreamCtx([]))
    client._client.stream = stream  # type: ignore[method-assign]  # noqa: SLF001

    with pytest.raises(LLMProjectionError) as exc_info:
        client.chat(messages=messages, tools=[], guard_context=_guard())

    assert expected_violation in exc_info.value.violations
    assert stream.call_count == 0


def test_cross_provider_fallback_rebinds_active_ingress_before_actual_send(
    build_test_engine, fake_settings, monkeypatch
) -> None:
    """Fallback rebuild must bind its own exact ingress validator context."""

    def raise_500(_calls):
        raise LLMHTTPError("primary unavailable", status_code=500, provider="primary")

    engine, primary = build_test_engine([raise_500])
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    settings = dataclasses.replace(
        fake_settings,
        model_providers_raw=json.dumps(
            {
                "primary": {
                    "api_key_env": "LLM_API_KEY",
                    "base_url": "https://primary.invalid/v1",
                    "models": {"fake-model": {}},
                },
                "deepseek": {
                    "api_key_env": "LLM_API_KEY",
                    "base_url": "https://fallback.invalid/v1",
                    "models": {"deepseek-backup": {}},
                },
            }
        ),
        model_fallbacks_raw="deepseek/deepseek-backup",
    )
    engine.settings = settings
    registry = load_registry(settings)
    primary.model = "fake-model"
    fallback = _client(
        provider="deepseek",
        model="deepseek-backup",
        base_url="https://fallback.invalid/v1",
    )
    stream = mock.Mock(
        return_value=_FakeStreamCtx(
            [
                'data: {"choices":[{"delta":{"content":"fallback-ok"}}]}',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                "data: [DONE]",
            ]
        )
    )
    fallback._client.stream = stream  # type: ignore[method-assign]  # noqa: SLF001
    pool = ModelClientPool(  # type: ignore[arg-type]
        registry=registry,
        default_client=primary,
        model_fallbacks_raw=settings.model_fallbacks_raw,
    )
    pool._provider_cache["deepseek/deepseek-backup"] = fallback  # noqa: SLF001
    engine.llm_pool = pool

    sid = engine.session.create()
    result = engine.run(sid, "CURRENT-INGRESS")

    assert result.final_answer == "fallback-ok"
    assert stream.call_count == 1
    payload = stream.call_args.kwargs["json"]
    assert "_active_run_ingress_ref" not in json.dumps(payload)
    matching = [
        item
        for item in payload["messages"]
        if item.get("role") == "user"
        and str(item.get("content") or "").endswith("CURRENT-INGRESS")
    ]
    assert len(matching) == 1


def test_same_provider_disconnect_retry_reuses_only_the_validated_exact_packet() -> None:
    """Zero-output transport retry may resend the same already-validated packet."""

    class _DisconnectBeforeOutput(_FakeStreamCtx):
        def __init__(self) -> None:
            super().__init__([])

        def iter_lines(self):
            raise httpx.RemoteProtocolError("peer closed before first delta")
            yield  # pragma: no cover - keeps this a generator

    client = _client(provider="deepseek")
    sends: list[dict] = []

    def _stream(*_args, **kwargs):
        sends.append(deepcopy(kwargs["json"]))
        if len(sends) == 1:
            return _DisconnectBeforeOutput()
        return _FakeStreamCtx(
            [
                'data: {"choices":[{"delta":{"content":"retry-ok"}}]}',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                "data: [DONE]",
            ]
        )

    client._client.stream = mock.Mock(side_effect=_stream)  # type: ignore[method-assign]  # noqa: SLF001
    resp = client.chat(messages=_canonical_messages(), tools=[], guard_context=_guard())

    assert resp.content == "retry-ok"
    assert len(sends) == 2
    assert sends[0] == sends[1]
    assert "_active_run_ingress_ref" not in json.dumps(sends[0])
    assert sends[0]["messages"][1]["content"] == "DELEGATED"


def test_same_provider_disconnect_after_output_never_replays_packet() -> None:
    """Any emitted delta makes transport replay unsafe and therefore forbidden."""

    class _DisconnectAfterOutput(_FakeStreamCtx):
        def __init__(self) -> None:
            super().__init__([])

        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"PARTIAL"}}]}'
            raise httpx.RemoteProtocolError("peer closed after output")

    client = _client(provider="deepseek")
    stream = mock.Mock(return_value=_DisconnectAfterOutput())
    client._client.stream = stream  # type: ignore[method-assign]  # noqa: SLF001

    with pytest.raises(LLMNetworkError):
        client.chat(messages=_canonical_messages(), tools=[], guard_context=_guard())

    assert stream.call_count == 1
    sent = stream.call_args.kwargs["json"]
    assert "_active_run_ingress_ref" not in json.dumps(sent)


def test_retracted_user_actual_send_never_rehydrates_attachment_excerpt() -> None:
    message = Message(
        role="user",
        content="ORIGINAL-SECRET",
        source=MessageSource.USER,
        metadata={
            "retracted": True,
            "attachments": [
                {
                    "ref": "attachment://secret",
                    "filename": "secret.txt",
                    "excerpt": "ATTACHMENT-SECRET",
                }
            ],
        },
    ).to_llm_dict()
    message["_active_run_ingress_ref"] = "7"
    client = _client(provider="glm")
    stream = mock.Mock(
        return_value=_FakeStreamCtx(
            [
                'data: {"choices":[{"delta":{"content":"ok"}}]}',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                "data: [DONE]",
            ]
        )
    )
    client._client.stream = stream  # type: ignore[method-assign]  # noqa: SLF001
    client.chat(
        messages=[{"role": "system", "content": "SYS"}, message],
        tools=[],
        guard_context=_guard(),
    )

    payload_text = json.dumps(stream.call_args.kwargs["json"], ensure_ascii=False)
    assert "[RETRACTED]" in payload_text
    assert "ORIGINAL-SECRET" not in payload_text
    assert "ATTACHMENT-SECRET" not in payload_text
    assert "attachment_facts" not in payload_text
    assert "_active_run_ingress_ref" not in payload_text


def test_message_time_actual_send_renders_fact_and_strips_internal_carriers() -> None:
    client = _client(provider="glm")
    stream = mock.Mock(
        return_value=_FakeStreamCtx(
            [
                'data: {"choices":[{"delta":{"content":"ok"}}]}',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                "data: [DONE]",
            ]
        )
    )
    client._client.stream = stream  # type: ignore[method-assign]  # noqa: SLF001
    client.chat(
        messages=[
            {"role": "system", "content": "SYS"},
            {
                "role": "user",
                "content": "TASK",
                "_message_time_ts": 1_700_000_000.0,
                "_active_run_ingress_ref": "7",
            },
        ],
        tools=[],
        guard_context=_guard(),
    )

    payload = stream.call_args.kwargs["json"]
    user = payload["messages"][1]
    assert user["content"].startswith("[message_time system_local=")
    assert user["content"].endswith("]\nTASK")
    wire = json.dumps(payload)
    assert "_message_time_ts" not in wire
    assert "_active_run_ingress_ref" not in wire
