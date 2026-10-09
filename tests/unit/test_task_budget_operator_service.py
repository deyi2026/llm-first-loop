"""I5-G IPC/auth test: no production keys, no real Web or Provider traffic."""

from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from Crypto.PublicKey import ECC

from llm_loop.event_log.model import build_message_payload
from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_dispatch import exact_workspace_scope
from llm_loop.resources.task_budget_event_authority import _event_hash
from llm_loop.resources.task_budget_operator_proof import OfflineOperatorApprovalSigner
from llm_loop.resources.task_budget_operator_service import (
    OperatorServiceConfig,
    _peer_uid,
    _private_budget_key,
    _read_frame,
    _send_frame,
    request_operator_approved_budget,
    serve_authenticated_connection,
)
from llm_loop.resources.task_budget_positive_authority import verify_positive_proof
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError


def _pem(key: ECC.EccKey, *, public: bool = False) -> bytes:
    data = (key.public_key() if public else key).export_key(format="PEM")
    return data.encode() if isinstance(data, str) else data


def _fixture(tmp_path: Path):
    events = EventStore(tmp_path / "events")
    event = events.append_durable_human_message(
        "web-session", build_message_payload(
            index=0, role="user", source="user", content="trusted",
            metadata={"origin_layer": "user_instruction", "program_origin": False},
        ),
    )
    op_key, budget_key = ECC.generate(curve="Ed25519"), ECC.generate(curve="Ed25519")
    approver = OfflineOperatorApprovalSigner(
        key_id="operator-a", operator_id="alice", private_key_pem=_pem(op_key),
    )
    op1 = approver.sign_exact_event(
        event_id=event.event_id, event_seq=event.seq,
        event_sha256=_event_hash(event), session_id="web-session",
        workspace_scope=exact_workspace_scope(str(tmp_path)),
    )
    trust_file = tmp_path / "trusted-operator-public.json"
    trust_info: dict[str, Any] = {
        "schema": "task-budget-operator-trust/v1",
        "public_keys": {"operator-a": _pem(op_key, public=True).decode()},
        "authorized_operators": {"alice": "operator-a"},
        "revoked_keys": [],
    }

    def save_trust() -> None:
        trust_file.write_text(json.dumps(trust_info))
        trust_file.chmod(0o600)

    save_trust()
    key_file = tmp_path / "budget-only.key"
    key_file.write_bytes(_pem(budget_key))
    key_file.chmod(0o600)
    audit_dir = tmp_path / "audit"
    audit_dir.mkdir(mode=0o700)
    config = OperatorServiceConfig(
        socket_path=tmp_path / "issuer.sock",
        expected_web_uid=os.geteuid() + 1,  # deliberately NOT this test process
        event_store_dir=tmp_path / "events", workspace_root=tmp_path,
        budget_key_file=key_file, budget_key_id="budget-k1",
        operator_trust_file=trust_file, audit_dir=audit_dir,
    )
    request = {
        "protocol": "I5-G-op1-glm-v1", "event_id": event.event_id,
        "session_id": "web-session", "operator_proof": op1,
    }
    return config, event, request, trust_info, save_trust, _pem(budget_key, public=True)


def _exchange(config: OperatorServiceConfig, request: dict[str, Any], monkeypatch) -> dict:
    left, right = socket.socketpair()
    try:
        # A test-only fake peer UID validates protocol logic, NOT OS account
        # isolation. Real serve_forever never accepts a peer UID override.
        monkeypatch.setattr(
            "llm_loop.resources.task_budget_operator_service._peer_uid",
            lambda _conn: config.expected_web_uid,
        )
        worker = threading.Thread(target=serve_authenticated_connection, args=(config, left))
        worker.start()
        _send_frame(right, request)
        result = _read_frame(right, 12_288)
        worker.join(timeout=2)
        assert not worker.is_alive()
        return result
    finally:
        left.close()
        right.close()


def test_service_denies_same_unseparated_os_account(tmp_path: Path) -> None:
    config, _event, _request, _trust, _save, _key = _fixture(tmp_path)
    config.validate_boundary()
    from dataclasses import replace

    with pytest.raises(TaskBudgetDeniedError):
        replace(config, expected_web_uid=os.geteuid()).validate_boundary()


def test_kernel_peer_uid_is_not_supplied_by_request() -> None:
    left, right = socket.socketpair()
    try:
        assert _peer_uid(left) == os.geteuid()
    finally:
        left.close()
        right.close()


def test_isolated_service_accepts_exact_operator_signature_and_audits(tmp_path: Path, monkeypatch) -> None:
    config, event, request, _trust, _save, public = _fixture(tmp_path)
    response = _exchange(config, request, monkeypatch)
    assert response["ok"] is True
    proof = response["positive_proof"]
    data = verify_positive_proof(proof, {"budget-k1": public})
    assert data["event_id"] == event.event_id
    assert data["grant"]["limits"]["physical_attempts"] == 1
    audit_file = config.audit_dir / "approvals.jsonl"
    records = [json.loads(line) for line in audit_file.read_text().splitlines()]
    assert len(records) == 1
    assert records[0]["event_id"] == event.event_id
    assert "operator_proof" not in records[0]
    assert "positive_proof" not in records[0]
    assert _pem(ECC.import_key(_private_budget_key(config.budget_key_file))) != public


@pytest.mark.parametrize("cause", [
    "web_cookie", "event_mismatch", "session_mismatch", "revoked", "bad_proof",
])
def test_service_denies_unapproved_request_without_audit(tmp_path: Path, monkeypatch, cause: str) -> None:
    config, _event, request, trust, save, _public = _fixture(tmp_path)
    if cause == "web_cookie":
        request["operator_proof"] = "browser-cookie"
    elif cause == "event_mismatch":
        request["event_id"] = "00000000-0000-4000-8000-000000000001"
    elif cause == "session_mismatch":
        request["session_id"] = "foreign"
    elif cause == "revoked":
        trust["revoked_keys"] = ["operator-a"]
        save()
    elif cause == "bad_proof":
        proof = request["operator_proof"]
        request["operator_proof"] = proof[:-1] + ("A" if proof[-1] != "A" else "B")
    response = _exchange(config, request, monkeypatch)
    assert response == {"ok": False, "reason": "operator_approval_denied"}
    assert not (config.audit_dir / "approvals.jsonl").exists()


def test_real_same_uid_peer_rejected_even_with_valid_op1(tmp_path: Path) -> None:
    config, _event, request, _trust, _save, _public = _fixture(tmp_path)
    left, right = socket.socketpair()
    try:
        worker = threading.Thread(target=serve_authenticated_connection, args=(config, left))
        worker.start()
        _send_frame(right, request)
        assert _read_frame(right, 12_288) == {
            "ok": False, "reason": "operator_approval_denied",
        }
        worker.join(timeout=2)
        assert not worker.is_alive()
    finally:
        left.close()
        right.close()
    assert not (config.audit_dir / "approvals.jsonl").exists()


def test_private_budget_key_world_access_or_symlink_is_denied(tmp_path: Path) -> None:
    config, _event, _request, _trust, _save, _public = _fixture(tmp_path)
    config.budget_key_file.chmod(0o644)
    with pytest.raises(TaskBudgetDeniedError):
        _private_budget_key(config.budget_key_file)
    config.budget_key_file.chmod(0o600)
    alias = tmp_path / "alias.key"
    alias.symlink_to(config.budget_key_file)
    with pytest.raises(TaskBudgetDeniedError):
        _private_budget_key(alias)


def test_audit_fsync_failure_suppresses_signed_response(tmp_path: Path, monkeypatch) -> None:
    config, _event, request, _trust, _save, _public = _fixture(tmp_path)
    monkeypatch.setattr(
        "llm_loop.resources.task_budget_operator_service.os.fsync",
        mock.Mock(side_effect=OSError("audit disk fault")),
    )
    response = _exchange(config, request, monkeypatch)
    assert response == {"ok": False, "reason": "operator_approval_denied"}


def test_socket_client_api_can_receive_only_a_signed_token(tmp_path: Path, monkeypatch) -> None:
    config, event, request, _trust, _save, public = _fixture(tmp_path)
    monkeypatch.setattr(
        "llm_loop.resources.task_budget_operator_service._peer_uid",
        lambda _conn: config.expected_web_uid,
    )
    # macOS AF_UNIX sun_path is short (~104 bytes); the MCP pytest temp
    # root can be much longer. Bind a *relative* socket name from temp cwd.
    monkeypatch.chdir(tmp_path)
    socket_name = "issuer.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(socket_name)
        listener.listen(1)

        def accept_one() -> None:
            accepted, _address = listener.accept()
            with accepted:
                serve_authenticated_connection(config, accepted)

        worker = threading.Thread(target=accept_one)
        worker.start()
        result = request_operator_approved_budget(
            socket_path=socket_name, event_id=event.event_id,
            session_id="web-session", operator_proof=request["operator_proof"],
        )
        worker.join(timeout=2)
        assert not worker.is_alive()
    assert verify_positive_proof(result, {"budget-k1": public})["event_id"] == event.event_id
