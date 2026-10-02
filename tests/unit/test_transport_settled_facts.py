"""P0-2 GAP-RESP-1 (Phase C1): settled response facts on transport attempts.

Design DESIGN-20261002 §2 GAP-RESP-1: ``provider.transport.settled`` gains
additive ``finish_reason``, ``normalized_response_hmac`` (+ ``_key_id``, keyed
GAP-POL-1 primitive) and ``provider_observed_model`` (protocol echo; Web paths
structurally omit it). Missing facts are omitted, never fabricated. HMAC oracle
is computed independently in this file (stdlib).
"""

from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
from collections.abc import Callable
from typing import Any
from unittest import mock

import httpx
import pytest

from llm_loop.event_log.store import EventStore
from llm_loop.llm.chatgpt_web import ChatGPTWebModelClient
from llm_loop.llm.client import LLMClient
from llm_loop.llm.deepseek_web import DeepSeekWebModelClient
from llm_loop.resources.contracts import ExecutionClass, ServicePriority
from llm_loop.resources.governor import ResourceGovernor
from llm_loop.resources.provider_calls import ProviderCallCoordinator
from llm_loop.resources.provider_settlement import (  # noqa: F401
    ProviderAttemptKind,
    ProviderCallOutcome,
    ProviderCallPurpose,
    ProviderCallSettlementJournal,
    ProviderCallSite,
    ProviderTransportOutcome,
    bind_provider_call_site,
)
from llm_loop.resources.transport_observation import ShadowTransportRecorder

_SECRET_HEX = "ab" * 32


def _oracle(data: bytes, secret_hex: str = _SECRET_HEX) -> str:
    return hmac_mod.new(bytes.fromhex(secret_hex), data, hashlib.sha256).hexdigest()


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _projection(content: Any, reasoning: Any = None, tool_calls: Any = None) -> bytes:
    return _canonical(
        {
            "content": content,
            "reasoning_content": reasoning,
            "tool_calls": tool_calls or [],
        }
    )


def _set_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LFL_CONTENT_HMAC_SECRET", _SECRET_HEX)
    monkeypatch.setenv("LFL_CONTENT_HMAC_KEY_ID", "unit-env-key")


def _clear_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LFL_CONTENT_HMAC_SECRET", raising=False)
    monkeypatch.delenv("LFL_CONTENT_HMAC_KEY_ID", raising=False)


def _journal(tmp_path):
    store = EventStore(tmp_path / "events")
    journal = ProviderCallSettlementJournal(store, clock=lambda: 100.0)
    recorder = ShadowTransportRecorder(clock=lambda: 100.0)
    recorder.set_settlement_journal(journal)
    return store, journal, recorder


def _site(call, *, provider_id: str = "deepseek", model_id: str = "deepseek-flash"):
    return ProviderCallSite(
        call=call,
        attempt_kind=ProviderAttemptKind.PRIMARY,
        site_index=0,
        provider_id=provider_id,
        model_id=model_id,
    )


def _call_journal(journal) -> Any:
    return journal.open_call(
        session_id="s1",
        idempotency_key="task:s1:turn:2:round:1",
        owner_ref="task:s1:round:1",
        execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND,
        purpose=ProviderCallPurpose.TASK,
    )


def _settled_payloads(store, journal, session_id: str = "s1") -> list[dict[str, Any]]:
    return [
        event.payload
        for event in store.read(session_id)
        if event.type == journal.TRANSPORT_SETTLED
    ]


class _FakeStreamCtx:
    def __init__(self, lines, status_code: int = 200) -> None:
        self._lines = lines
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        yield from self._lines


def test_openai_settled_carries_response_facts(tmp_path, monkeypatch):
    _set_key_env(monkeypatch)
    store, journal, recorder = _journal(tmp_path)
    call = _call_journal(journal)

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            'data: {"model":"deepseek-flash","usage":{"prompt_tokens":4,"completion_tokens":1,"total_tokens":5}}\n\n'
            'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/event-stream"},
            content=body.encode(),
        )

    client = LLMClient(
        api_key="k",
        base_url="https://provider.invalid/v1",
        model="deepseek-flash",
        provider="deepseek",
        guard_enabled=False,
        transport_observer=recorder,
    )
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        with bind_provider_call_site(_site(call)):
            response = client.chat([{"role": "user", "content": "x"}], tools=[])
    finally:
        client.close()

    assert response.finish_reason == "stop"
    settled = _settled_payloads(store, journal)
    assert len(settled) == 1
    payload = settled[0]
    assert payload["outcome"] == "success"
    assert payload["finish_reason"] == "stop"
    assert payload["provider_observed_model"] == "deepseek-flash"
    assert payload["normalized_response_hmac"] == _oracle(_projection("ok"))
    assert payload["normalized_response_hmac_key_id"] == "unit-env-key"


@pytest.mark.parametrize(
    ("wire_protocol", "lines", "finish_reason", "observed_model", "content"),
    [
        (
            "anthropic",
            [
                'data: {"type":"message_start","message":{"model":"claude-3-7-x","usage":{"input_tokens":10,"output_tokens":0}}}',
                'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hi"}}',
                'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}',
                "data: [DONE]",
            ],
            "end_turn",
            "claude-3-7-x",
            "hi",
        ),
        (
            "google",
            [
                'data: {"modelVersion":"gemini-2.5-pro","candidates":[{"content":{"parts":[{"text":"hi"}],"role":"model"},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":5,"candidatesTokenCount":2}}',
                "data: [DONE]",
            ],
            "STOP",
            "gemini-2.5-pro",
            "hi",
        ),
    ],
)
def test_native_protocol_settled_carries_model_echo(
    tmp_path, monkeypatch, wire_protocol, lines, finish_reason, observed_model, content
):
    _set_key_env(monkeypatch)
    store, journal, recorder = _journal(tmp_path)
    call = _call_journal(journal)
    stream = mock.Mock()
    stream.return_value = _FakeStreamCtx(lines)
    client = LLMClient(
        api_key="k",
        base_url="https://fake.local/v1",
        model="m-1",
        provider=wire_protocol,
        wire_protocol=wire_protocol,
        guard_enabled=False,
        transport_observer=recorder,
    )
    client._client.stream = stream  # type: ignore[method-assign]
    try:
        with bind_provider_call_site(
            _site(call, provider_id=client.provider, model_id=client.model)
        ):
            list(client.chat_stream([{"role": "user", "content": "x"}], tools=[]))
    finally:
        client.close()

    settled = _settled_payloads(store, journal)
    assert len(settled) == 1
    payload = settled[0]
    assert payload["outcome"] == "success"
    assert payload["finish_reason"] == finish_reason
    assert payload["provider_observed_model"] == observed_model
    assert payload["normalized_response_hmac"] == _oracle(_projection(content))


def test_lms_settled_omits_structurally_absent_facts(tmp_path, monkeypatch):
    _set_key_env(monkeypatch)
    store, journal, recorder = _journal(tmp_path)
    call = _call_journal(journal)
    stream = mock.Mock()
    stream.return_value = _FakeStreamCtx(
        [
            'data: {"type":"message.delta","content":"ok"}',
            'data: {"type":"chat.end","result":{"stats":{"input_tokens":5,"total_output_tokens":1}}}',
            "data: [DONE]",
        ]
    )
    client = LLMClient(
        api_key="k",
        base_url="https://fake.local/v1",
        model="m-1",
        provider="lms-chat",
        wire_protocol="lms-chat",
        guard_enabled=False,
        transport_observer=recorder,
    )
    client._client.stream = stream  # type: ignore[method-assign]
    try:
        with bind_provider_call_site(
            _site(call, provider_id=client.provider, model_id=client.model)
        ):
            list(client.chat_stream([{"role": "user", "content": "x"}], tools=[]))
    finally:
        client.close()

    settled = _settled_payloads(store, journal)
    assert len(settled) == 1
    payload = settled[0]
    assert payload["outcome"] == "success"
    assert "finish_reason" not in payload  # lms 协议无 stop 回显
    assert "provider_observed_model" not in payload
    assert payload["normalized_response_hmac"] == _oracle(_projection("ok"))


def test_missing_hmac_key_settled_keeps_facts_but_omits_hmac(tmp_path, monkeypatch):
    _clear_key_env(monkeypatch)
    store, journal, recorder = _journal(tmp_path)
    call = _call_journal(journal)

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            'data: {"model":"deepseek-flash"}\n\n'
            'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/event-stream"},
            content=body.encode(),
        )

    client = LLMClient(
        api_key="k",
        base_url="https://provider.invalid/v1",
        model="deepseek-flash",
        provider="deepseek",
        guard_enabled=False,
        transport_observer=recorder,
    )
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        with bind_provider_call_site(_site(call)):
            client.chat([{"role": "user", "content": "x"}], tools=[])
    finally:
        client.close()

    payload = _settled_payloads(store, journal)[0]
    assert payload["finish_reason"] == "stop"
    assert payload["provider_observed_model"] == "deepseek-flash"
    assert "normalized_response_hmac" not in payload
    assert "normalized_response_hmac_key_id" not in payload


class _NullRuntimeAdapter:
    def note_provider_call(self, *args: Any, **kwargs: Any) -> None:
        return None


class _Transport:
    def __init__(self, *, raw: dict | None = None) -> None:
        self.requests: list[tuple[dict, float | None]] = []
        self._raw = raw

    def exchange(self, request: dict, *, timeout_s: float | None = None) -> dict:
        self.requests.append((request, timeout_s))
        if self._raw is not None:
            return self._raw
        return {
            "protocol": request["protocol"],
            "request_id": request["request_id"],
            "content": "ok",
            "tool_calls": [],
            "finish_reason": "stop",
        }


def _web_flow(tmp_path, make_client: Callable[[ShadowTransportRecorder], Any]):
    store = EventStore(tmp_path / "events")
    journal = ProviderCallSettlementJournal(store)
    recorder = ShadowTransportRecorder()
    recorder.set_settlement_journal(journal)
    coordinator = ProviderCallCoordinator(
        ResourceGovernor(),
        local_runtime=_NullRuntimeAdapter(),
        settlement_journal=journal,
    )
    client = make_client(recorder)
    call = coordinator.open_shadow_call_for_client(
        client,
        session_id="s-web",
        idempotency_key="task:s-web:turn:1:round:1",
        owner_ref="task:s-web:round:1",
        execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND,
        purpose=ProviderCallPurpose.TASK,
    )
    captured: list[Exception] = []
    try:
        # 外层捕获：错误必须穿过 attempt scope 的 __exit__ 完成 error settle
        # （内层吞掉会被结算成 success），再由断言侧核对异常类型。
        with coordinator.bind_shadow_call_site(
            call, client, attempt_kind=ProviderAttemptKind.PRIMARY, site_index=0
        ):
            client.chat([{"role": "user", "content": "x"}], tools=[])
    except Exception as exc:  # noqa: BLE001 — settle 已完成；测试按预期核对
        captured.append(exc)
    return captured, _settled_payloads(store, journal, "s-web")


@pytest.mark.parametrize(
    "make_client",
    [
        lambda observer: ChatGPTWebModelClient(_Transport(), transport_observer=observer),
        lambda observer: DeepSeekWebModelClient(_Transport(), transport_observer=observer),
    ],
    ids=["chatgpt", "deepseek"],
)
def test_web_settled_carries_finish_reason_and_hmac_without_observed_model(
    tmp_path, monkeypatch, make_client
):
    _set_key_env(monkeypatch)
    errors, settled = _web_flow(tmp_path, make_client)
    assert errors == []
    assert len(settled) == 1
    payload = settled[0]
    assert payload["outcome"] == "success"
    assert payload["finish_reason"] == "stop"
    assert payload["normalized_response_hmac"] == _oracle(_projection("ok"))
    assert payload["normalized_response_hmac_key_id"] == "unit-env-key"
    assert "provider_observed_model" not in payload  # Web 回显结构性不存在，不伪造


def test_web_protocol_error_settles_as_error_without_finish_reason(tmp_path, monkeypatch):
    from llm_loop.llm.chatgpt_web import ChatGPTModelProtocolError

    _set_key_env(monkeypatch)
    bad_transport = _Transport(raw={"protocol": "lfl-model/0.1", "request_id": "x"})
    errors, settled = _web_flow(
        tmp_path, lambda observer: ChatGPTWebModelClient(bad_transport, transport_observer=observer)
    )
    assert len(errors) == 1
    assert isinstance(errors[0], ChatGPTModelProtocolError)
    assert len(settled) == 1
    payload = settled[0]
    assert payload["outcome"] == "error"
    assert payload["error_type"] == "ChatGPTModelProtocolError"
    assert "finish_reason" not in payload


def test_note_settled_response_facts_without_active_attempt_is_noop(tmp_path):
    _unused_store, _unused_journal, recorder = _journal(tmp_path)
    recorder.note_settled_response_facts(  # 无 active capture：静默 no-op
        finish_reason="stop", provider_observed_model="m"
    )
    assert recorder.snapshot() == ()


def test_journal_settle_response_facts_additive_and_conflict(tmp_path):
    store = EventStore(tmp_path / "events")
    journal = ProviderCallSettlementJournal(store, clock=lambda: 100.0)
    call = _call_journal(journal)
    site = _site(call)
    attempt = journal.open_transport_attempt(site, transport_retry_index=0)

    def _settle(**kwargs):
        base = dict(
            session_id="s1",
            attempt=attempt,
            outcome=ProviderTransportOutcome.SUCCESS,
            usage=None,
            usage_observations=0,
            status_code=None,
            provider_code=None,
            retry_after_seconds=None,
            rate_limits=(),
            error_type=None,
        )
        base.update(kwargs)
        return journal.settle_transport_attempt(**base)

    payload = _settle(finish_reason="stop", provider_observed_model="m")
    assert payload["finish_reason"] == "stop"
    assert payload["provider_observed_model"] == "m"
    assert "normalized_response_hmac" not in payload
    # 幂等重复 settle：同值不新增事件
    again = _settle(finish_reason="stop", provider_observed_model="m")
    assert again["finish_reason"] == "stop"
    assert len(_settled_payloads(store, journal)) == 1
    # 同 attempt 不同事实 → 冲突
    with pytest.raises((ValueError, RuntimeError)):
        _settle(finish_reason="length")
