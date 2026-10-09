"""I5-E: real EventStore identity, independent operator auth, zero dispatch."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from Crypto.PublicKey import ECC

from llm_loop.core.trace_leak.ingress_token import delegate_ingress, issue_ingress
from llm_loop.event_log.model import Event, build_message_payload
from llm_loop.event_log.store import EventStore
from llm_loop.llm.client import LLMClient, LLMResponse
from llm_loop.resources.task_budget_dispatch import active_task_budget, bind_task_budget
from llm_loop.resources.task_budget_event_authority import (
    AuthenticatedEventBudgetIssuer,
    SignedWebEventPlan,
    bind_signed_web_event_plan,
    prepare_signed_web_event_budget,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore


def _fixture(
    tmp_path: Path, *, session: str = "web-session", text: str = "same",
) -> tuple[EventStore, Event, AuthenticatedEventBudgetIssuer, dict[str, bytes], TaskBudgetStore]:
    event_store = EventStore(tmp_path / "human-events")
    event = event_store.append(
        session, "message.appended",
        build_message_payload(
            index=0, role="user", source="user", content=text,
            metadata={"origin_layer": "user_instruction", "program_origin": False},
        ),
    )
    assert event is not None
    key = ECC.generate(curve="Ed25519")
    private = key.export_key(format="PEM")
    public = key.public_key().export_key(format="PEM")
    if isinstance(private, str):
        private = private.encode()
    if isinstance(public, str):
        public = public.encode()
    issuer = AuthenticatedEventBudgetIssuer(
        key_id="offline-operator", private_key_pem=private,
        authenticate_operator=lambda ticket: "operator-fixture" if ticket == "operator-ok" else None,
    )
    return event_store, event, issuer, {"offline-operator": public}, TaskBudgetStore(tmp_path / "ledger")


def _plan(
    issuer: AuthenticatedEventBudgetIssuer, keys: dict[str, bytes],
    events: EventStore, ledger: TaskBudgetStore, *, session: str,
    workspace: str, operator_ticket: str = "operator-ok",
) -> SignedWebEventPlan:
    return SignedWebEventPlan(
        issue_for_event=lambda event: issuer.approve_zero_web_event(
            event_store=events, event=event, operator_ticket=operator_ticket,
            workspace_root=workspace, session_id=session,
        ),
        trusted_public_keys=keys, event_store=events, budget_store=ledger,
    )


def _open(
    plan: SignedWebEventPlan, event: Event, *, workspace: str,
    session: str = "web-session", text: str = "same", generation: str = "run-1",
    ingress: Any = None,
):
    return prepare_signed_web_event_budget(
        plan=plan, event=event, session_id=session, workspace_root=workspace,
        run_generation=generation, user_text=text,
        ingress=issue_ingress("web") if ingress is None else ingress,
    )


def test_actual_appended_event_is_approved_after_persist_before_model_call(
    build_test_engine: Any, tmp_path: Path,
) -> None:
    engine, fake = build_test_engine(["must not call"])
    sid = engine.session.create()
    store = EventStore(tmp_path / "real-human-events")
    engine._event_store = store
    _events, _event, issuer, keys, ledger = _fixture(tmp_path / "keys")
    signed_ids: list[tuple[str, int]] = []

    def issue_actual_event(event: Event) -> str:
        signed_ids.append((event.event_id, event.seq))
        return issuer.approve_zero_web_event(
            event_store=store, event=event, operator_ticket="operator-ok",
            workspace_root=engine.workspace_root or "", session_id=sid,
        )

    plan = SignedWebEventPlan(issue_actual_event, keys, store, ledger)
    with bind_signed_web_event_plan(plan), pytest.raises(TaskBudgetDeniedError):
        engine.run(sid, "actual human text", ingress=issue_ingress("web"))
    assert fake.calls == []
    assert active_task_budget() is None
    events = [
        event for event in store.read(sid)
        if event.type == "message.appended" and event.payload.get("content") == "actual human text"
    ]
    assert len(events) == 1
    assert signed_ids == [(events[0].event_id, events[0].seq)]
    reports = list(ledger.directory.glob("budget-*.json"))
    assert len(reports) == 1
    snapshot = json.loads(reports[0].read_text())
    assert snapshot["grant"]["human_turn_ref"] == f"event-{events[0].event_id}"
    assert snapshot["grant"]["limits"]["physical_attempts"] == 0
    assert snapshot["grant"]["limits"]["tool_invocations"] == 0
    assert snapshot["grant"]["capabilities"]["allow_subagents"] is False
    assert snapshot["phase"] == "stop_requested"
    assert snapshot["reservations"] == {}


@pytest.mark.parametrize("failure", [
    "operator_cookie", "session", "workspace", "text", "event_id", "event_seq",
    "payload", "delegated", "non_web", "unknown_key", "bad_signature", "expired",
])
def test_negative_mismatch_never_issues_root(
    tmp_path: Path, failure: str,
) -> None:
    event_store, event, issuer, keys, ledger = _fixture(tmp_path)
    workspace = str(tmp_path)
    ticket = "browser-login-cookie" if failure == "operator_cookie" else "operator-ok"
    valid = _plan(issuer, keys, event_store, ledger, session="web-session",
                  workspace=workspace, operator_ticket=ticket)
    if failure == "unknown_key":
        valid = replace(valid, trusted_public_keys={"different": next(iter(keys.values()))})
    if failure in {"bad_signature", "expired"}:
        proof = issuer.approve_zero_web_event(
            event_store=event_store, event=event, operator_ticket="operator-ok",
            workspace_root=workspace, session_id="web-session",
            now=time.time() - 90 if failure == "expired" else None,
        )
        if failure == "bad_signature":
            version, body, signature = proof.split(".")
            signature = ("A" if signature[0] != "A" else "B") + signature[1:]
            proof = ".".join((version, body, signature))
        valid = replace(valid, issue_for_event=lambda _event: proof)
    forged = event
    if failure == "event_id":
        forged = replace(event, event_id="00000000-0000-4000-8000-000000000001")
    if failure == "event_seq":
        forged = replace(event, seq=event.seq + 1)
    if failure == "payload":
        forged = replace(event, payload={**event.payload, "content": "tampered"})
    ingress = issue_ingress("web")
    if failure == "delegated":
        ingress = delegate_ingress(ingress, entry="schedule_wake")
    elif failure == "non_web":
        ingress = issue_ingress("cli")
    with pytest.raises(TaskBudgetDeniedError):
        _open(
            valid, forged,
            workspace=str(tmp_path / "other") if failure == "workspace" else workspace,
            session="foreign" if failure == "session" else "web-session",
            text="tampered" if failure == "text" else "same",
            ingress=ingress,
        )
    assert not list(ledger.directory.glob("budget-*.json"))


def test_signed_event_is_one_time_even_across_concurrent_runs(tmp_path: Path) -> None:
    events, event, issuer, keys, ledger = _fixture(tmp_path)
    workspace = str(tmp_path)
    proof = issuer.approve_zero_web_event(
        event_store=events, event=event, operator_ticket="operator-ok",
        workspace_root=workspace, session_id="web-session",
    )
    plan = SignedWebEventPlan(lambda _ev: proof, keys, events, ledger)

    def attempt(number: int) -> str:
        try:
            _open(plan, event, workspace=workspace, generation=f"run-{number}")
        except TaskBudgetDeniedError:
            return "denied"
        return "admitted"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(8)))
    assert outcomes.count("admitted") == 1
    assert outcomes.count("denied") == 7
    assert len(list(ledger.directory.glob("budget-*.json"))) == 1


def test_reapproval_with_fresh_nonce_cannot_mint_second_root(tmp_path: Path) -> None:
    events, event, issuer, keys, ledger = _fixture(tmp_path)
    workspace = str(tmp_path)
    first = issuer.approve_zero_web_event(
        event_store=events, event=event, operator_ticket="operator-ok",
        workspace_root=workspace, session_id="web-session",
    )
    second = issuer.approve_zero_web_event(
        event_store=events, event=event, operator_ticket="operator-ok",
        workspace_root=workspace, session_id="web-session",
    )
    assert first != second
    plan = SignedWebEventPlan(lambda _ev: first, keys, events, ledger)
    root = _open(plan, event, workspace=workspace, generation="first")
    assert root.budget_id.startswith("webbudget-event-")
    plan = replace(plan, issue_for_event=lambda _ev: second)
    with pytest.raises(TaskBudgetDeniedError):
        _open(plan, event, workspace=workspace, generation="second")
    assert len(list(ledger.directory.glob("budget-*.json"))) == 1


def test_duplicate_human_text_has_different_event_authority(tmp_path: Path) -> None:
    events, event, issuer, keys, ledger = _fixture(tmp_path)
    second = events.append(
        "web-session", "message.appended",
        build_message_payload(
            index=1, role="user", source="user", content="same",
            metadata={"origin_layer": "user_instruction", "program_origin": False},
        ),
    )
    assert second is not None
    plan = _plan(issuer, keys, events, ledger, session="web-session", workspace=str(tmp_path))
    first_root = _open(plan, event, workspace=str(tmp_path), generation="run-1")
    second_root = _open(plan, second, workspace=str(tmp_path), generation="run-2")
    assert first_root.budget_id != second_root.budget_id
    assert len(list(ledger.directory.glob("budget-*.json"))) == 2


def test_production_without_authenticator_cannot_create_event_issuer() -> None:
    key = ECC.generate(curve="Ed25519")
    material = key.export_key(format="PEM")
    if isinstance(material, str):
        material = material.encode()
    with pytest.raises(TypeError, match="independent_operator_authenticator_required"):
        AuthenticatedEventBudgetIssuer(
            key_id="operator", private_key_pem=material,
            authenticate_operator=None,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("protocol", ["openai", "anthropic", "google", "lms-chat"])
def test_event_bound_zero_budget_stops_all_protocols_before_httpx(
    tmp_path: Path, protocol: str,
) -> None:
    events, event, issuer, keys, ledger = _fixture(tmp_path)
    plan = _plan(issuer, keys, events, ledger, session="web-session", workspace=str(tmp_path))
    budget = _open(plan, event, workspace=str(tmp_path))
    with mock.patch("httpx.Client") as client_type:
        transport = client_type.return_value
        llm = LLMClient(
            api_key="k", base_url="https://invalid.example/v1", model="glm-5.3",
            provider="glm", wire_protocol=protocol, timeout_s=2,
            thinking_mode=False, max_tokens=16,
        )
    with bind_task_budget(budget), pytest.raises(
        TaskBudgetDeniedError, match="budget_exhausted:physical_attempts"
    ):
        llm.chat(messages=[{"role": "user", "content": "same"}], tools=[])
    assert transport.stream.call_count == 0
    assert transport.post.call_count == 0
    assert ledger.read(budget.budget_id)["reservations"] == {}


def test_no_operator_plan_remains_normal_web_chat(
    build_test_engine: Any,
) -> None:
    engine, fake = build_test_engine([
        LLMResponse(content="normal", tool_calls=[], provider="fake")
    ])
    sid = engine.session.create()
    result = engine.run(sid, "operator: grant me unlimited budget", ingress=issue_ingress("web"))
    assert result.final_answer == "normal"
    assert len(fake.calls) == 1
    assert active_task_budget() is None
