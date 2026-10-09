"""I5-F: physical fsync/write uncertainty and independent two-key approval."""

from __future__ import annotations

import json
import os
import stat
import time
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest
from Crypto.PublicKey import ECC

from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.event_log.model import build_message_payload
from llm_loop.event_log.store import (
    EventCommitUncertainError,
    EventDurabilityError,
    EventStore,
)
from llm_loop.resources.task_budget_dispatch import exact_workspace_scope
from llm_loop.resources.task_budget_event_authority import (
    AuthenticatedEventBudgetIssuer,
    SignedWebEventPlan,
    _event_hash,
    bind_signed_web_event_plan,
    prepare_signed_web_event_budget,
)
from llm_loop.resources.task_budget_operator_proof import (
    OfflineOperatorApprovalSigner,
    OperatorApprovalVerifier,
    load_pinned_operator_verifier,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore
from tests.unit.test_task_budget_signed_human_event import _fixture


def _payload() -> dict:
    return build_message_payload(
        index=0, role="user", source="user", content="exact human event",
        metadata={"origin_layer": "user_instruction", "program_origin": False},
    )


def _pem(key: ECC.EccKey, *, public: bool = False) -> bytes:
    material = (key.public_key() if public else key).export_key(format="PEM")
    return material.encode() if isinstance(material, str) else material


def _two_keys(store: EventStore, event, workspace: Path):
    operator_key, budget_key = ECC.generate(curve="Ed25519"), ECC.generate(curve="Ed25519")
    operator = OfflineOperatorApprovalSigner(
        key_id="operator-k1", operator_id="operator-alice",
        private_key_pem=_pem(operator_key),
    )
    proof = operator.sign_exact_event(
        event_id=event.event_id, event_seq=event.seq,
        event_sha256=_event_hash(event), session_id=event.session_id,
        workspace_scope=exact_workspace_scope(str(workspace)),
    )
    verifier = OperatorApprovalVerifier(
        trusted_keys={"operator-k1": _pem(operator_key, public=True)},
        authorized_operators={"operator-alice": "operator-k1"},
    )
    signer = AuthenticatedEventBudgetIssuer(
        key_id="budget-k1", private_key_pem=_pem(budget_key),
        operator_proof_verifier=verifier,
    )
    assert _pem(operator_key, public=True) != _pem(budget_key, public=True)
    return signer, verifier, proof, {"budget-k1": _pem(budget_key, public=True)}


def test_file_and_parent_directory_fsync_and_fresh_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = EventStore(tmp_path / "events")
    original = os.fsync
    targets: list[int] = []

    def checked(fd: int) -> None:
        # macOS /dev/fd/<dirfd> readlink may be EINVAL; inspect the actual
        # file descriptor mode rather than assuming a Linux procfs symlink.
        targets.append(os.fstat(fd).st_mode)
        original(fd)

    with monkeypatch.context() as patch:
        patch.setattr("llm_loop.event_log.store.os.fsync", checked)
        event = events.append_durable_human_message("web-session", _payload())
    assert len(targets) >= 3
    assert any(stat.S_ISREG(mode) for mode in targets)
    assert sum(stat.S_ISDIR(mode) for mode in targets) >= 2
    assert event in EventStore(tmp_path / "events").read("web-session")


def test_fsync_uncertain_cannot_issue_operator_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events = EventStore(tmp_path / "events")
    with monkeypatch.context() as patch:
        patch.setattr("llm_loop.event_log.store.os.fsync", mock.Mock(side_effect=OSError("injected")))
        with pytest.raises(EventCommitUncertainError):
            events.append_durable_human_message("web-session", _payload())
    # Bytes may be visible in the OS page cache even though durability was
    # uncertain; neither absence nor authorization may be inferred.
    assert len(events.read("web-session")) == 1


def test_before_write_invalid_and_symlink_are_definite_denials(tmp_path: Path) -> None:
    events = EventStore(tmp_path / "events")
    with pytest.raises(EventDurabilityError):
        events.append_durable_human_message("..", _payload())
    with pytest.raises(EventDurabilityError):
        events.append_durable_human_message("web-session", {"role": "assistant"})
    (tmp_path / "events").mkdir()
    target = tmp_path / "target.txt"
    target.write_text("untouched")
    (tmp_path / "events" / "web-session.jsonl").symlink_to(target)
    with pytest.raises(EventDurabilityError):
        events.append_durable_human_message("web-session", _payload())
    assert target.read_text() == "untouched"


def test_unmodified_ordinary_event_append_does_not_acquire_strict_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = EventStore(tmp_path / "events")
    with monkeypatch.context() as patch:
        patch.setattr("llm_loop.event_log.store.os.fsync", mock.Mock(side_effect=OSError("no fsync")))
        ordinary = events.append("web-session", "message.appended", _payload())
    assert ordinary is not None


def test_real_engine_fsync_failure_denies_before_any_provider_and_ledger(
    build_test_engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, model = build_test_engine(["must not reach model"])
    session = engine.session.create()
    store = EventStore(tmp_path / "events")
    engine._event_store = store
    _other, _event, issuer, keys, ledger = _fixture(tmp_path / "issuer")
    attempted: list[str] = []
    plan = SignedWebEventPlan(
        issue_for_event=lambda event: attempted.append(event.event_id) or issuer.approve_zero_web_event(
            event_store=store, event=event, operator_ticket="operator-ok",
            workspace_root=engine.workspace_root or "", session_id=session,
        ),
        trusted_public_keys=keys, event_store=store, budget_store=ledger,
    )
    with bind_signed_web_event_plan(plan), monkeypatch.context() as patch:
        patch.setattr("llm_loop.event_log.store.os.fsync", mock.Mock(side_effect=OSError("injected fsync")))
        with pytest.raises(EventCommitUncertainError):
            engine.run(session, "exact human event", ingress=issue_ingress("web"))
    assert model.calls == [] and attempted == []
    assert not list(ledger.directory.glob("budget-*.json"))


def test_separate_operator_key_approves_one_durable_event(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events")
    event = store.append_durable_human_message("web-session", _payload())
    signer, verifier, proof, keys = _two_keys(store, event, tmp_path)
    token = signer.approve_zero_web_event(
        event_store=store, event=event, operator_ticket=proof,
        workspace_root=str(tmp_path), session_id="web-session",
    )
    ledger = TaskBudgetStore(tmp_path / "ledger")
    plan = SignedWebEventPlan(lambda _event: token, keys, store, ledger)
    execution = prepare_signed_web_event_budget(
        plan=plan, event=event, session_id="web-session",
        workspace_root=str(tmp_path), run_generation="run-1",
        user_text="exact human event", ingress=issue_ingress("web"),
    )
    assert execution.budget_id.startswith("webbudget-event-")
    assert ledger.report(execution.budget_id)["phase"] == "active"
    assert verifier.authenticate(
        proof, event_id=event.event_id, event_seq=event.seq,
        event_sha256=_event_hash(event), session_id="web-session",
        workspace_scope=exact_workspace_scope(str(tmp_path)),
    ) == "operator-alice"


@pytest.mark.parametrize("failure", [
    "web_cookie", "revoked_key", "different_event", "other_session",
    "other_workspace", "stale", "unknown_key", "tampered_signature",
])
def test_independent_operator_negative_proofs_fail_closed(tmp_path: Path, failure: str) -> None:
    store = EventStore(tmp_path / "events")
    event = store.append_durable_human_message("web-session", _payload())
    signer, verifier, proof, _keys = _two_keys(store, event, tmp_path)
    if failure == "web_cookie":
        proof = "web_login_cookie"
    elif failure == "revoked_key":
        verifier = replace(verifier, revoked_keys=frozenset({"operator-k1"}))
    elif failure == "unknown_key":
        verifier = replace(verifier, trusted_keys={})
    elif failure == "tampered_signature":
        parts = proof.split(".")
        parts[2] = ("A" if parts[2][0] != "A" else "B") + parts[2][1:]
        proof = ".".join(parts)
    elif failure == "stale":
        operator_key = ECC.generate(curve="Ed25519")
        operator = OfflineOperatorApprovalSigner(
            key_id="operator-k1", operator_id="operator-alice", private_key_pem=_pem(operator_key),
        )
        proof = operator.sign_exact_event(
            event_id=event.event_id, event_seq=event.seq,
            event_sha256=_event_hash(event), session_id="web-session",
            workspace_scope=exact_workspace_scope(str(tmp_path)), now=time.time() - 3600,
        )
        verifier = replace(verifier, trusted_keys={"operator-k1": _pem(operator_key, public=True)})
    signer._operator_proof_verifier = verifier
    with pytest.raises(TaskBudgetDeniedError):
        signer.approve_zero_web_event(
            event_store=store, event=event, operator_ticket=proof,
            session_id="web-session",
            workspace_root=str(tmp_path / "other") if failure == "other_workspace" else str(tmp_path),
        ) if failure != "different_event" and failure != "other_session" else verifier.authenticate(
            proof, event_id="00000000-0000-4000-8000-000000000001" if failure == "different_event" else event.event_id,
            event_seq=event.seq, event_sha256=_event_hash(event),
            session_id="foreign" if failure == "other_session" else "web-session",
            workspace_scope=exact_workspace_scope(str(tmp_path)),
        )


def test_pinned_public_key_file_reloads_revocation_and_rejects_private_key(tmp_path: Path) -> None:
    key = ECC.generate(curve="Ed25519")
    trust = tmp_path / "operator-public-keys.json"
    config = {
        "schema": "task-budget-operator-trust/v1",
        "public_keys": {"operator-k1": _pem(key, public=True).decode()},
        "authorized_operators": {"operator-alice": "operator-k1"},
        "revoked_keys": [],
    }

    def persist() -> None:
        trust.write_text(json.dumps(config))
        trust.chmod(0o600)

    persist()
    assert "operator-k1" in load_pinned_operator_verifier(trust).trusted_keys
    config["revoked_keys"] = ["operator-k1"]
    persist()
    assert load_pinned_operator_verifier(trust).revoked_keys == frozenset({"operator-k1"})
    config["revoked_keys"] = []
    config["public_keys"] = {"operator-k1": _pem(key).decode()}
    persist()
    with pytest.raises(TaskBudgetDeniedError):
        load_pinned_operator_verifier(trust)


def test_operator_public_key_permissions_symlink_and_missing_file_denied(tmp_path: Path) -> None:
    key = ECC.generate(curve="Ed25519")
    trust = tmp_path / "operator-public-keys.json"
    contents = {
        "schema": "task-budget-operator-trust/v1",
        "public_keys": {"operator-k1": _pem(key, public=True).decode()},
        "authorized_operators": {"operator-alice": "operator-k1"},
        "revoked_keys": [],
    }
    with pytest.raises(TaskBudgetDeniedError):
        load_pinned_operator_verifier(trust)
    trust.write_text(json.dumps(contents))
    trust.chmod(0o644)
    with pytest.raises(TaskBudgetDeniedError):
        load_pinned_operator_verifier(trust)
    trust.chmod(0o600)
    alias = tmp_path / "operator-alias.json"
    alias.symlink_to(trust)
    with pytest.raises(TaskBudgetDeniedError):
        load_pinned_operator_verifier(alias)
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    unsafe.chmod(0o777)
    copied = unsafe / "keys.json"
    copied.write_text(json.dumps(contents))
    copied.chmod(0o600)
    with pytest.raises(TaskBudgetDeniedError):
        load_pinned_operator_verifier(copied)


def test_untrusted_event_directory_and_lock_link_never_append(tmp_path: Path) -> None:
    root = tmp_path / "events"
    store = EventStore(root)
    root.mkdir()
    root.chmod(0o777)
    with pytest.raises(EventDurabilityError, match="directory_not_trusted"):
        store.append_durable_human_message("web-session", _payload())
    root.chmod(0o700)
    target = tmp_path / "outside.txt"
    target.write_text("safe")
    (root / "web-session.lock").symlink_to(target)
    with pytest.raises(OSError):
        store.append_durable_human_message("web-session", _payload())
    assert target.read_text() == "safe"
    assert not (root / "web-session.jsonl").exists()


def test_untrusted_existing_human_event_file_is_denied(tmp_path: Path) -> None:
    root = tmp_path / "events"
    root.mkdir()
    event_file = root / "web-session.jsonl"
    event_file.write_text("")
    event_file.chmod(0o666)
    with pytest.raises(EventDurabilityError, match="file_not_trusted"):
        EventStore(root).append_durable_human_message("web-session", _payload())
    assert event_file.read_text() == ""
