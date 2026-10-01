"""P0-2 GAP-ID-1: web model clients must settle provider call facts.

Audit AUDIT-20261001-P0-1 GAP-ID-1 / design DESIGN-20261002 Phase A2: web
transports historically produced zero provider.call / provider.transport.attempt
settlement facts because the clients lacked a bound transport_observer, so
ProviderCallCoordinator.open_shadow_call_for_client silently returned None on
every web path.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from llm_loop.event_log.store import EventStore
from llm_loop.llm.chatgpt_web import MODEL_PROTOCOL, ChatGPTWebModelClient
from llm_loop.llm.deepseek_web import DeepSeekWebModelClient
from llm_loop.resources.contracts import ExecutionClass, ServicePriority
from llm_loop.resources.governor import ResourceGovernor
from llm_loop.resources.provider_calls import ProviderCallCoordinator
from llm_loop.resources.provider_settlement import (
    ProviderAttemptKind,
    ProviderCallOutcome,
    ProviderCallPurpose,
    ProviderCallSettlementJournal,
)
from llm_loop.resources.transport_observation import ShadowTransportRecorder


class _NullRuntimeAdapter:
    def note_provider_call(self, *args: Any, **kwargs: Any) -> None:
        return None


class _Transport:
    def __init__(self) -> None:
        self.requests: list[tuple[dict, float | None]] = []

    def exchange(self, request: dict, *, timeout_s: float | None = None) -> dict:
        self.requests.append((request, timeout_s))
        return {
            "protocol": MODEL_PROTOCOL,
            "request_id": request["request_id"],
            "content": "ok",
            "tool_calls": [],
            "finish_reason": "stop",
        }


def _coordinator(tmp_path) -> tuple[ProviderCallCoordinator, ProviderCallSettlementJournal, ShadowTransportRecorder]:
    store = EventStore(tmp_path / "events")
    journal = ProviderCallSettlementJournal(store)
    recorder = ShadowTransportRecorder()
    recorder.set_settlement_journal(journal)
    coordinator = ProviderCallCoordinator(
        ResourceGovernor(),
        local_runtime=_NullRuntimeAdapter(),
        settlement_journal=journal,
    )
    return coordinator, journal, recorder


def _assert_web_client_settles(tmp_path, make_client: Callable[[ShadowTransportRecorder], Any]) -> None:
    coordinator, journal, recorder = _coordinator(tmp_path)
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
    assert call is not None, "web client must carry settlement identity (GAP-ID-1)"

    with coordinator.bind_shadow_call_site(
        call, client, attempt_kind=ProviderAttemptKind.PRIMARY, site_index=0
    ):
        response = client.chat([{"role": "user", "content": "hi"}], [])
    assert response.content == "ok"
    coordinator.settle_shadow_call(call, ProviderCallOutcome.SUCCESS)

    snapshot = journal.snapshot_call(call)
    assert snapshot["attempts_opened"] == 1
    assert snapshot["attempts_settled"] == 1
    assert snapshot["call_outcome"] == "success"
    assert snapshot["attempts"][0]["provider_id"] == client.provider
    assert snapshot["attempts"][0]["model_id"] == client.model


def test_chatgpt_web_client_settles_provider_call_attempts(tmp_path):
    _assert_web_client_settles(
        tmp_path, lambda observer: ChatGPTWebModelClient(_Transport(), transport_observer=observer)
    )


def test_deepseek_web_client_settles_provider_call_attempts(tmp_path):
    _assert_web_client_settles(
        tmp_path, lambda observer: DeepSeekWebModelClient(_Transport(), transport_observer=observer)
    )
