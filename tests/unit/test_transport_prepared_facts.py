"""P0-2 GAP-REQ-1 (Phase B2): prepared facts on every transport attempt.

Design DESIGN-20261002 §2 GAP-REQ-1: write-before-send prepared facts ride the
``provider.transport.opened`` event as an additive ``prepared`` mapping:
``payload_hmac`` / ``payload_hmac_key_id`` (keyed, GAP-POL-1), ``projected_bytes``,
``representation`` and ``controls``. Old opened events without ``prepared`` must
keep hydrating. HMAC oracle is computed independently in this file (stdlib).
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
    bind_provider_call_site,
)
from llm_loop.resources.transport_observation import ShadowTransportRecorder

_SECRET_HEX = "ab" * 32  # 64 hex chars -> 32 bytes


def _oracle(data: bytes, secret_hex: str = _SECRET_HEX) -> str:
    return hmac_mod.new(bytes.fromhex(secret_hex), data, hashlib.sha256).hexdigest()


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _set_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LFL_CONTENT_HMAC_SECRET", _SECRET_HEX)
    monkeypatch.setenv("LFL_CONTENT_HMAC_KEY_ID", "unit-env-key")


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


def _opened_payloads(store, journal, session_id):
    return [
        event.payload for event in store.read(session_id) if event.type == journal.TRANSPORT_OPENED
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


def _call_journal(journal) -> Any:
    return journal.open_call(
        session_id="s1",
        idempotency_key="task:s1:turn:2:round:1",
        owner_ref="task:s1:round:1",
        execution_class=ExecutionClass.FOREGROUND_TASK,
        service_priority=ServicePriority.P0_FOREGROUND,
        purpose=ProviderCallPurpose.TASK,
    )


def test_openai_transport_opened_carries_prepared_hash_facts(tmp_path, monkeypatch):
    _set_key_env(monkeypatch)
    store, journal, recorder = _journal(tmp_path)
    call = _call_journal(journal)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read())
        body = (
            'data: {"usage":{"prompt_tokens":4,"completion_tokens":1,"total_tokens":5}}\n\n'
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
            response = client.chat([{"role": "user", "content": "x"}], tools=[], timeout_s=12.5)
    finally:
        client.close()

    assert response.content == "ok"
    payloads = _opened_payloads(store, journal, "s1")
    assert len(payloads) == 1
    prepared = payloads[0]["prepared"]
    assert prepared["representation"] == "openai-json"
    canonical = _canonical(captured["body"])
    assert prepared["payload_hmac"] == _oracle(canonical)
    assert prepared["payload_hmac_key_id"] == "unit-env-key"
    assert prepared["projected_bytes"] == len(canonical)
    controls = prepared["controls"]
    assert controls["provider"] == "deepseek"
    assert controls["model"] == "deepseek-flash"
    assert controls["wire_protocol"] == "openai"
    assert "max_tokens" in controls
    assert controls["timeout_s"] == 12.5
    assert "reasoning_mode" in controls


_PROTOCOL_CASES = [
    (
        "anthropic",
        "anthropic-converted",
        [
            'data: {"type":"message_start","message":{"usage":{"input_tokens":10,"output_tokens":0}}}',
            'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hi"}}',
            'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"}}',
            "data: [DONE]",
        ],
    ),
    (
        "google",
        "google-payload",
        [
            'data: {"candidates":[{"content":{"parts":[{"text":"hi"}],"role":"model"},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":5,"candidatesTokenCount":2}}',
            "data: [DONE]",
        ],
    ),
    (
        "lms-chat",
        "lms-chat-json",
        [
            'data: {"type":"message.delta","content":"ok"}',
            'data: {"type":"chat.end","result":{"stats":{"input_tokens":5,"total_output_tokens":1}}}',
            "data: [DONE]",
        ],
    ),
]


@pytest.mark.parametrize(("wire_protocol", "representation", "lines"), _PROTOCOL_CASES)
def test_native_protocol_opened_carries_representation(
    tmp_path, monkeypatch, wire_protocol, representation, lines
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

    payloads = _opened_payloads(store, journal, "s1")
    assert len(payloads) == 1
    prepared = payloads[0]["prepared"]
    assert prepared["representation"] == representation
    assert prepared["payload_hmac_key_id"] == "unit-env-key"
    sent = stream.call_args.kwargs["json"]
    assert prepared["payload_hmac"] == _oracle(_canonical(sent))
    assert prepared["projected_bytes"] == len(_canonical(sent))
    assert prepared["controls"]["timeout_s"] == pytest.approx(client.timeout_s, rel=None, abs=1e-9)


class _NullRuntimeAdapter:
    def note_provider_call(self, *args: Any, **kwargs: Any) -> None:
        return None


class _Transport:
    def __init__(self) -> None:
        self.requests: list[tuple[dict, float | None]] = []

    def exchange(self, request: dict, *, timeout_s: float | None = None) -> dict:
        self.requests.append((request, timeout_s))
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
    with coordinator.bind_shadow_call_site(
        call, client, attempt_kind=ProviderAttemptKind.PRIMARY, site_index=0
    ):
        response = client.chat([{"role": "user", "content": "hi"}], [])
    coordinator.settle_shadow_call(call, ProviderCallOutcome.SUCCESS)
    assert response.content == "ok"
    payloads = _opened_payloads(store, journal, "s-web")
    assert len(payloads) == 1
    return payloads[0]["prepared"]


def test_chatgpt_web_opened_carries_rendered_text_prepared(tmp_path, monkeypatch):
    _set_key_env(monkeypatch)
    from llm_loop.llm.chatgpt_transport import ChatGPTWebPageTransport

    transport = _Transport()
    prepared = _web_flow(
        tmp_path, lambda observer: ChatGPTWebModelClient(transport, transport_observer=observer)
    )
    request = transport.requests[0][0]
    rendered = ChatGPTWebPageTransport._render_request(request)  # noqa: SLF001
    assert prepared["representation"] == "chatgpt-rendered-text"
    assert prepared["payload_hmac"] == _oracle(rendered.encode("utf-8"))
    assert prepared["payload_hmac_key_id"] == "unit-env-key"
    assert prepared["projected_bytes"] == len(rendered.encode("utf-8"))
    controls = prepared["controls"]
    assert controls["model"] == request.get("model")
    assert controls["controls_channel"] == "rendered_preamble"
    assert "reasoning_effort_requested" in controls


def test_deepseek_web_opened_carries_dsml_prepared(tmp_path, monkeypatch):
    _set_key_env(monkeypatch)
    from llm_loop.llm.deepseek_transport import DeepSeekWebPageTransport

    transport = _Transport()
    prepared = _web_flow(
        tmp_path, lambda observer: DeepSeekWebModelClient(transport, transport_observer=observer)
    )
    request = transport.requests[0][0]
    rendered = DeepSeekWebPageTransport._render_request(request)  # noqa: SLF001
    assert prepared["representation"] == "deepseek-rendered-dsml"
    assert prepared["payload_hmac"] == _oracle(rendered.encode("utf-8"))
    assert prepared["projected_bytes"] == len(rendered.encode("utf-8"))


def test_missing_hmac_key_leaves_honest_absence_not_forgery(tmp_path, monkeypatch):
    _set_key_env(monkeypatch)
    import llm_loop.resources.content_digest as content_digest

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("no key material")

    monkeypatch.setattr(content_digest, "resolve_content_hmac_key", _boom)
    transport = _Transport()
    prepared = _web_flow(
        tmp_path, lambda observer: ChatGPTWebModelClient(transport, transport_observer=observer)
    )
    assert prepared["representation"] == "chatgpt-rendered-text"
    assert prepared["projected_bytes"] > 0
    assert "payload_hmac" not in prepared
    assert "payload_hmac_key_id" not in prepared


def test_opened_event_without_prepared_still_rehydrates(tmp_path):
    store, journal, recorder = _journal(tmp_path)
    call = _call_journal(journal)
    with (
        bind_provider_call_site(_site(call)),
        recorder.transport_attempt(
            provider_id="deepseek", model_id="deepseek-flash", transport_retry_index=0
        ),
    ):
        pass

    payloads = _opened_payloads(store, journal, "s1")
    assert len(payloads) == 1
    assert "prepared" not in payloads[0]

    reloaded = ProviderCallSettlementJournal(EventStore(tmp_path / "events"))
    snapshot = reloaded.snapshot_call(call.call_id, session_id=call.session_id)
    assert snapshot["attempts_opened"] == 1
    assert snapshot["attempts_settled"] == 1
    assert snapshot["attempts_complete"] is True
