"""I5-G: one exact GLM physical attempt after two independent signatures."""

# ruff: noqa: SIM117 - nested contexts intentionally isolate pre-send failures

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from Crypto.PublicKey import ECC

from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.event_log.model import build_message_payload
from llm_loop.event_log.store import EventStore
from llm_loop.llm.client import LLMClient
from llm_loop.resources.task_budget_dispatch import (
    active_task_budget,
    bind_task_budget,
    checked_provider_attempt,
    exact_workspace_scope,
    has_dispatched_attempt,
)
from llm_loop.resources.task_budget_event_authority import (
    SignedWebEventPlan,
    _event_hash,
    prepare_signed_web_event_budget,
)
from llm_loop.resources.task_budget_operator_proof import (
    OfflineOperatorApprovalSigner,
    OperatorApprovalVerifier,
)
from llm_loop.resources.task_budget_positive_authority import (
    POLICY,
    PROFILE,
    ApprovedOneAttemptIssuer,
    verify_positive_proof,
)
from llm_loop.resources.task_budget_process_transport import (
    IsolatedTransportProfile,
    bind_isolated_provider_transport,
    isolated_provider_stream,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore

_GLM_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def _pem(key: ECC.EccKey, *, public: bool = False) -> bytes:
    value = (key.public_key() if public else key).export_key(format="PEM")
    return value.encode() if isinstance(value, str) else value


def _fixture(tmp_path: Path):
    store = EventStore(tmp_path / "events")
    event = store.append_durable_human_message(
        "web-session",
        build_message_payload(
            index=0, role="user", source="user", content="call once",
            metadata={"origin_layer": "user_instruction", "program_origin": False},
        ),
    )
    op_key, signer_key = ECC.generate(curve="Ed25519"), ECC.generate(curve="Ed25519")
    operator = OfflineOperatorApprovalSigner(
        key_id="op-key", operator_id="alice", private_key_pem=_pem(op_key),
    )
    approval = operator.sign_exact_event(
        event_id=event.event_id, event_seq=event.seq,
        event_sha256=_event_hash(event), session_id="web-session",
        workspace_scope=exact_workspace_scope(str(tmp_path)),
    )
    verifier = OperatorApprovalVerifier(
        trusted_keys={"op-key": _pem(op_key, public=True)},
        authorized_operators={"alice": "op-key"},
    )
    issuer = ApprovedOneAttemptIssuer(
        key_id="budget-key", private_key_pem=_pem(signer_key),
        operator_verifier=verifier,
    )
    proof = issuer.approve_exact_event(
        event_store=store, event=event, operator_proof=approval,
        workspace_root=str(tmp_path), session_id="web-session",
    )
    keys = {"budget-key": _pem(signer_key, public=True)}
    ledger = TaskBudgetStore(tmp_path / "ledger")
    plan = SignedWebEventPlan(
        issue_for_event=lambda _: proof,
        trusted_public_keys=keys,
        event_store=store,
        budget_store=ledger,
        allow_one_physical_attempt=True,
    )
    return store, event, verifier, issuer, approval, proof, plan, ledger


def _open(plan: SignedWebEventPlan, event: Any, tmp_path: Path, *, generation="run-1"):
    return prepare_signed_web_event_budget(
        plan=plan, event=event, session_id="web-session",
        workspace_root=str(tmp_path), run_generation=generation,
        user_text="call once", ingress=issue_ingress("web"),
    )


def test_two_party_signed_one_attempt_exact_fixed_policy(tmp_path: Path) -> None:
    store, event, _verifier, _issuer, _approval, proof, plan, ledger = _fixture(tmp_path)
    assert proof.startswith("tb3.")
    data = verify_positive_proof(proof, plan.trusted_public_keys)
    assert data["event_id"] == event.event_id
    assert data["grant"]["policy_version"] == POLICY
    assert data["grant"]["profile"] == PROFILE
    execution = _open(plan, event, tmp_path)
    row = ledger.read(execution.budget_id)
    assert row["grant"]["limits"]["physical_attempts"] == 1
    assert row["grant"]["limits"]["tool_invocations"] == 0
    assert row["grant"]["limits"]["input_tokens"] is None
    assert row["grant"]["limits"]["logical_calls"] is None
    assert row["grant"]["capabilities"]["allow_wake"] is False
    assert row["grant"]["capabilities"]["allow_subagents"] is False
    assert row["grant"]["provider_identity"] == "glm"
    assert row["grant"]["exact_model_ref"] == "glm-5.3"
    assert active_task_budget() is None
    assert event in EventStore(store._dir).read("web-session")


def test_default_zero_plan_refuses_valid_positive_proof(tmp_path: Path) -> None:
    _store, event, _verifier, _issuer, _approval, _proof, plan, ledger = _fixture(tmp_path)
    with pytest.raises(TaskBudgetDeniedError):
        _open(replace(plan, allow_one_physical_attempt=False), event, tmp_path)
    assert not list(ledger.directory.glob("budget-*.json"))


def test_one_event_reapproval_with_new_nonce_denied_by_root_cas(tmp_path: Path) -> None:
    store, event, _verifier, issuer, approval, _proof, plan, ledger = _fixture(tmp_path)
    _open(plan, event, tmp_path)
    other = issuer.approve_exact_event(
        event_store=store, event=event, operator_proof=approval,
        workspace_root=str(tmp_path), session_id="web-session",
    )
    with pytest.raises(TaskBudgetDeniedError):
        _open(replace(plan, issue_for_event=lambda _: other), event, tmp_path, generation="run-2")
    assert len(list(ledger.directory.glob("budget-*.json"))) == 1


@pytest.mark.parametrize("invalid", [
    "cookie", "revoked", "foreign_session", "foreign_workspace",
    "old_ticket", "other_event", "mutated_event",
])
def test_operator_proof_mismatch_never_creates_positive_token(tmp_path: Path, invalid: str) -> None:
    store, event, verifier, issuer, approval, _proof, _plan, ledger = _fixture(tmp_path)
    if invalid == "cookie":
        approval = "session-cookie-not-op1"
    elif invalid == "revoked":
        issuer._operator_verifier = replace(verifier, revoked_keys=frozenset({"op-key"}))
    elif invalid == "old_ticket":
        key = ECC.generate(curve="Ed25519")
        issuer._operator_verifier = OperatorApprovalVerifier(
            trusted_keys={"op-key": _pem(key, public=True)},
            authorized_operators={"alice": "op-key"},
        )
    elif invalid in {"other_event", "mutated_event"}:
        event = replace(event, event_id="00000000-0000-4000-8000-000000000001") if invalid == "other_event" else replace(event, payload={**event.payload, "content": "altered"})
    with pytest.raises(TaskBudgetDeniedError):
        issuer.approve_exact_event(
            event_store=store, event=event, operator_proof=approval,
            workspace_root=str(tmp_path / "other") if invalid == "foreign_workspace" else str(tmp_path),
            session_id="other" if invalid == "foreign_session" else "web-session",
        )
    assert not list(ledger.directory.glob("budget-*.json"))


@pytest.mark.parametrize("target", [
    ("openai", "glm-5.3", "openai", _GLM_URL),
    ("glm", "glm-5.2", "openai", _GLM_URL),
    ("glm", "glm-5.3", "anthropic", _GLM_URL),
    ("glm", "glm-5.3", "openai", "https://api.deepseek.com/v1/chat/completions"),
    ("glm", "glm-5.3", "openai", "http://open.bigmodel.cn/api/paas/v4"),
    ("glm", "glm-5.3", "openai", "https://open.bigmodel.cn.evil.test/api/v4"),
    ("glm", "glm-5.3", "openai", "https://open.bigmodel.cn:8443/api/v4"),
    ("glm", "glm-5.3", "openai", "https://open.bigmodel.cn/api/v4?key=malicious"),
])
def test_wrong_provider_or_route_never_consumes_attempt(
    tmp_path: Path, target: tuple[str, str, str, str],
) -> None:
    _store, event, _verifier, _issuer, _approval, _proof, plan, ledger = _fixture(tmp_path)
    execution = _open(plan, event, tmp_path)
    with bind_task_budget(execution), bind_isolated_provider_transport(IsolatedTransportProfile()):
        with pytest.raises(TaskBudgetDeniedError):
            with checked_provider_attempt(
                provider_id=target[0], model_id=target[1],
                wire_protocol=target[2], target_url=target[3],
            ):
                pytest.fail("request should not have been authorized")
    assert ledger.report(execution.budget_id)["used_or_reserved"]["physical_attempts"] == 0


def test_exact_one_physical_cas_and_unknown_billing_retained(tmp_path: Path) -> None:
    _store, event, _verifier, _issuer, _approval, _proof, plan, ledger = _fixture(tmp_path)
    execution = _open(plan, event, tmp_path)
    with bind_task_budget(execution):
        with pytest.raises(TaskBudgetDeniedError, match="exclusive_verified_process"):
            with checked_provider_attempt(
                provider_id="glm", model_id="glm-5.3",
                wire_protocol="openai", target_url=_GLM_URL,
            ):
                pytest.fail("isolation is mandatory")
        with bind_isolated_provider_transport(IsolatedTransportProfile()):
            with checked_provider_attempt(
                provider_id="glm", model_id="glm-5.3",
                wire_protocol="openai", target_url=_GLM_URL,
            ):
                assert has_dispatched_attempt(execution)
            assert not has_dispatched_attempt(execution)
            with pytest.raises(TaskBudgetDeniedError, match="budget_exhausted:physical_attempts"):
                with checked_provider_attempt(
                    provider_id="glm", model_id="glm-5.3",
                    wire_protocol="openai", target_url=_GLM_URL,
                ):
                    pytest.fail("second request must be forbidden")
    report = ledger.report(execution.budget_id)
    assert report["used_or_reserved"]["physical_attempts"] == 1
    assert report["physical_quiescence_verified"] is False
    assert len(report["outstanding_or_unknown"]) == 1


def test_direct_isolated_worker_without_dispatched_cas_cannot_connect(tmp_path: Path) -> None:
    import httpx

    _store, event, _verifier, _issuer, _approval, _proof, plan, ledger = _fixture(tmp_path)
    execution = _open(plan, event, tmp_path)
    with bind_task_budget(execution), bind_isolated_provider_transport(IsolatedTransportProfile()):
        with httpx.Client() as http:
            with pytest.raises(TaskBudgetDeniedError, match="without_dispatched_cas"):
                with isolated_provider_stream(
                    http, "POST", _GLM_URL,
                    json={"model": "glm-5.3", "messages": []},
                    headers={}, timeout=2.0,
                ):
                    pytest.fail("unauthorized direct worker")
    assert ledger.report(execution.budget_id)["used_or_reserved"]["physical_attempts"] == 0


@pytest.mark.parametrize("model,host", [
    ("glm-5.2", "https://open.bigmodel.cn/api/paas/v4"),
    ("glm-5.3", "https://api.deepseek.com/v1"),
    ("glm-5.3", "http://127.0.0.1:8898/v1"),
])
def test_actual_llm_client_route_mismatch_is_pre_http_and_pre_cas(
    tmp_path: Path, model: str, host: str,
) -> None:
    _store, event, _verifier, _issuer, _approval, _proof, plan, ledger = _fixture(tmp_path)
    execution = _open(plan, event, tmp_path)
    with mock.patch("httpx.Client") as http:
        http.return_value.stream.side_effect = AssertionError("HTTP must not be attempted")
        client = LLMClient(
            api_key="k", base_url=host, model=model, provider="glm",
            wire_protocol="openai", timeout_s=1.0, thinking_mode=False,
            max_tokens=8,
        )
    try:
        with bind_task_budget(execution), bind_isolated_provider_transport(IsolatedTransportProfile()):
            with pytest.raises(TaskBudgetDeniedError):
                client.chat(messages=[{"role": "user", "content": "offline"}], tools=[])
        assert http.return_value.stream.call_count == 0
        assert ledger.report(execution.budget_id)["used_or_reserved"]["physical_attempts"] == 0
    finally:
        client.close()
