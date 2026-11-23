"""Host-signed Task Lease: verification, revocation, replay and trust boundaries."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from llm_loop.core.task_capabilities import (
    CapabilityRequest,
    HostAuthorityFacts,
    resolve_capability,
)
from llm_loop.tools.task_authority import (
    RootOwnedTaskAuthority,
    TaskAuthorityError,
    _canonical_json,
    _read_separated_issuer_file,
    verify_signed_task_lease,
)

NOW = datetime(2026, 11, 19, 1, 0, tzinfo=UTC)


@pytest.fixture
def signed_receipts(tmp_path):
    key = Ed25519PrivateKey.generate()
    pub = key.public_key()
    pem = pub.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    kid = hashlib.sha256(
        pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ).hexdigest()[:16]
    root = str(tmp_path / "project-a")
    (tmp_path / "project-a").mkdir()
    (tmp_path / "project-b").mkdir()
    (tmp_path / "project-c").mkdir()
    lease = {
        "schema": "lfl.task-capability-lease/v1",
        "lease_id": "lease-12345678",
        "goal_id": "GOAL-a",
        "task_id": "TASK-a",
        "owner_session_id": "owner-session",
        "agent_id": "agent-1",
        "lane_id": "lane-1",
        "revision": 7,
        "issued_at": (NOW - timedelta(minutes=1)).isoformat(),
        "expires_at": (NOW + timedelta(minutes=30)).isoformat(),
        "authority_epoch": 2,
        "parent_lease_id": None,
        "resources": [
            {"kind": "project", "identity": root, "verbs": ["read", "write"]},
            {
                "kind": "project",
                "identity": str(tmp_path / "project-b"),
                "verbs": ["read", "write"],
            },
        ],
    }
    state = {
        "schema": "lfl.task-lease-state/v1",
        "lease_id": lease["lease_id"],
        "lease_revision": 7,
        "lease_sha256": hashlib.sha256(_canonical_json(lease)).hexdigest(),
        "authority_epoch": 2,
        "status": "active",
    }

    def sign(payload, domain):
        return json.dumps(
            {
                "key_id": kid,
                "payload": payload,
                "signature": base64.b64encode(
                    key.sign(domain + b"\x00" + _canonical_json(payload))
                ).decode("ascii"),
            },
            ensure_ascii=False,
        ).encode("utf-8")

    req = CapabilityRequest(
        "GOAL-a",
        "TASK-a",
        "owner-session",
        "agent-1",
        "lane-1",
        7,
        "project",
        str(tmp_path / "project-b" / "new.txt"),
        "write",
    )
    return pem, lease, state, sign, req


def _verify(bundle, *, lease=None, state=None, request=None, now=NOW):
    pem, original_lease, original_state, sign, original_request = bundle
    lease_payload = original_lease if lease is None else lease
    state_payload = original_state if state is None else state
    return verify_signed_task_lease(
        pem,
        sign(lease_payload, b"lfl.task-lease.v1"),
        sign(state_payload, b"lfl.task-lease-state.v1"),
        request or original_request,
        now=now,
    )


def test_valid_two_project_lease_with_runtime_fences(signed_receipts, tmp_path):
    claims = _verify(signed_receipts)
    req = signed_receipts[-1]
    facts = HostAuthorityFacts("verified", True, True, True, True)
    assert resolve_capability(req, lease=claims, facts=facts, now=NOW).allowed
    third = CapabilityRequest(
        req.goal_id,
        req.task_id,
        req.owner_session_id,
        req.agent_id,
        req.lane_id,
        req.expected_revision,
        "project",
        str(tmp_path / "project-c" / "not-allowed"),
        "write",
    )
    assert (
        resolve_capability(third, lease=claims, facts=facts, now=NOW).reason_code
        == "capability_scope_missing"
    )
    assert not resolve_capability(
        req, lease=claims, facts=HostAuthorityFacts("verified", False, True, True, True), now=NOW
    ).allowed
    assert not resolve_capability(
        req, lease=claims, facts=HostAuthorityFacts("verified", True, False, True, True), now=NOW
    ).allowed


def test_tampered_lease_rejected(signed_receipts):
    pem, lease, state, sign, req = signed_receipts
    signed = json.loads(sign(lease, b"lfl.task-lease.v1"))
    signed["payload"]["resources"][0]["verbs"].append("delete")
    with pytest.raises(TaskAuthorityError, match="authority_signature_invalid"):
        verify_signed_task_lease(
            pem, json.dumps(signed).encode(), sign(state, b"lfl.task-lease-state.v1"), req, now=NOW
        )


def test_revoked_or_stale_state_rejected(signed_receipts):
    _pem, _lease, state, _sign, _req = signed_receipts
    with pytest.raises(TaskAuthorityError, match="authority_lease_revoked"):
        _verify(signed_receipts, state={**state, "status": "revoked"})
    with pytest.raises(TaskAuthorityError, match="authority_state_stale"):
        _verify(signed_receipts, state={**state, "authority_epoch": 3})
    with pytest.raises(TaskAuthorityError, match="authority_state_stale"):
        _verify(signed_receipts, state={**state, "lease_revision": 6})


def test_expired_and_identity_mismatch_rejected(signed_receipts):
    req = signed_receipts[-1]
    with pytest.raises(TaskAuthorityError, match="authority_lease_expired"):
        _verify(signed_receipts, now=NOW + timedelta(hours=1))
    wrong = CapabilityRequest(
        req.goal_id,
        req.task_id,
        "another-session",
        req.agent_id,
        req.lane_id,
        req.expected_revision,
        req.kind,
        req.target,
        req.verb,
    )
    with pytest.raises(TaskAuthorityError, match="authority_identity_or_revision_mismatch"):
        _verify(signed_receipts, request=wrong)
    with pytest.raises(TaskAuthorityError, match="authority_time_invalid"):
        _verify(signed_receipts, now=NOW.replace(tzinfo=None))


def test_signed_root_scope_and_unknown_fields_rejected(signed_receipts):
    _pem, lease, state, _sign, _req = signed_receipts
    dangerous = {**lease, "resources": [{"kind": "project", "identity": "/", "verbs": ["write"]}]}
    with pytest.raises(TaskAuthorityError, match="authority_lease_schema_invalid"):
        _verify(
            signed_receipts,
            lease=dangerous,
            state={**state, "lease_sha256": hashlib.sha256(_canonical_json(dangerous)).hexdigest()},
        )
    unknown = {**lease, "is_superuser": True}
    with pytest.raises(TaskAuthorityError, match="authority_lease_schema_invalid"):
        _verify(
            signed_receipts,
            lease=unknown,
            state={**state, "lease_sha256": hashlib.sha256(_canonical_json(unknown)).hexdigest()},
        )


def test_untrusted_user_writable_authority_store_rejected(tmp_path, signed_receipts):
    root = tmp_path / "authority"
    root.mkdir()
    with pytest.raises(TaskAuthorityError, match="authority_store_untrusted"):
        RootOwnedTaskAuthority(root).verify("lease-12345678", signed_receipts[-1])


def test_invalid_key_and_oversized_receipt_rejected(signed_receipts):
    pem, lease, state, sign, req = signed_receipts
    with pytest.raises(TaskAuthorityError, match="authority_public_key_invalid"):
        verify_signed_task_lease(
            b"not a key",
            sign(lease, b"lfl.task-lease.v1"),
            sign(state, b"lfl.task-lease-state.v1"),
            req,
            now=NOW,
        )
    with pytest.raises(TaskAuthorityError, match="authority_receipt_size_invalid"):
        verify_signed_task_lease(
            pem, b" " * 65537, sign(state, b"lfl.task-lease-state.v1"), req, now=NOW
        )


def test_root_pinned_separate_issuer_uid_and_public_digest(signed_receipts, monkeypatch):
    from pathlib import Path

    import llm_loop.tools.task_authority as authority_module

    real_verify = authority_module.verify_signed_task_lease
    monkeypatch.setattr(
        authority_module,
        "verify_signed_task_lease",
        lambda *args, **kwargs: real_verify(*args, now=NOW, **kwargs),
    )
    pem, lease, state, sign, req = signed_receipts
    uid = os.getuid() + 1
    trust = {
        "schema": "lfl.task-authority-trust/v1",
        "issuer_uid": uid,
        "public_key_sha256": hashlib.sha256(pem).hexdigest(),
    }
    monkeypatch.setattr(
        authority_module,
        "_read_root_owned",
        lambda path: json.dumps(trust).encode() if path.name == "trust.json" else pem,
    )
    monkeypatch.setattr(
        authority_module,
        "_read_separated_issuer_file",
        lambda path, root, issuer_uid: (
            sign(lease, b"lfl.task-lease.v1")
            if path.parent.name == "leases"
            else sign(state, b"lfl.task-lease-state.v1")
        ),
    )
    root = RootOwnedTaskAuthority(
        Path("/Library/LFL-TaskHostIssuer/task-authority")
    )
    assert root.verify("lease-12345678", req).lease_id == "lease-12345678"
    trust["issuer_uid"] = os.getuid()
    with pytest.raises(TaskAuthorityError, match="authority_trust_config_invalid"):
        root.verify("lease-12345678", req)
    trust["issuer_uid"] = uid
    trust["public_key_sha256"] = "0" * 64
    with pytest.raises(TaskAuthorityError, match="authority_public_key_mismatch"):
        root.verify("lease-12345678", req)


def test_separated_issuer_file_rejects_symlink_hardlink_and_group_write(tmp_path):
    root = tmp_path / "authority"
    child = root / "leases"
    child.mkdir(parents=True)
    target = child / "lease-12345678.json"
    target.write_text("signed receipt")
    target.chmod(0o644)
    assert _read_separated_issuer_file(target, root, os.getuid()) == b"signed receipt"
    alias = child / "alias.json"
    alias.symlink_to(target)
    with pytest.raises(TaskAuthorityError, match="authority_store_unavailable"):
        _read_separated_issuer_file(alias, root, os.getuid())
    os.link(target, child / "hardlink.json")
    with pytest.raises(TaskAuthorityError, match="authority_store_untrusted"):
        _read_separated_issuer_file(target, root, os.getuid())
    (child / "hardlink.json").unlink()
    child.chmod(0o777)
    with pytest.raises(TaskAuthorityError, match="authority_store_untrusted"):
        _read_separated_issuer_file(target, root, os.getuid())


def test_issuer_owned_session_binding_real_signatures_and_ambiguity(
    tmp_path,
    signed_receipts,
    monkeypatch,
):
    pem, lease, state, sign, _request = signed_receipts
    root = tmp_path / "authority"
    (root / "leases").mkdir(parents=True)
    (root / "states").mkdir()
    session = lease["owner_session_id"]
    binding_dir = root / "bindings" / hashlib.sha256(session.encode()).hexdigest()
    binding_dir.mkdir(parents=True)
    monkeypatch.setattr(
        RootOwnedTaskAuthority,
        "_trust",
        lambda self: (os.getuid(), pem),
    )
    authority = RootOwnedTaskAuthority(root)
    clock = datetime.now(UTC)
    lease = {
        **lease,
        "issued_at": (clock - timedelta(minutes=1)).isoformat(),
        "expires_at": (clock + timedelta(hours=1)).isoformat(),
    }

    def publish(lease_payload, state_status="active"):
        lease_id = lease_payload["lease_id"]
        state_payload = {
            **state,
            "lease_id": lease_id,
            "lease_sha256": hashlib.sha256(_canonical_json(lease_payload)).hexdigest(),
            "status": state_status,
        }
        (root / "leases" / f"{lease_id}.json").write_bytes(
            sign(lease_payload, b"lfl.task-lease.v1")
        )
        (root / "states" / f"{lease_id}.json").write_bytes(
            sign(state_payload, b"lfl.task-lease-state.v1")
        )
        (binding_dir / f"{lease_id}.json").write_text(
            json.dumps(
                {
                    "schema": "lfl.task-session-binding/v1",
                    "owner_session_id": session,
                    "lease_id": lease_id,
                }
            )
        )

    publish(lease)
    first_claims = authority.discover_for_session(session)
    assert first_claims is not None
    assert first_claims.lease_id == lease["lease_id"]
    second = {**lease, "lease_id": "lease-abcdefgh"}
    publish(second)
    with pytest.raises(TaskAuthorityError, match="authority_bindings_ambiguous"):
        authority.discover_for_session(session)
    (root / "states" / f"{second['lease_id']}.json").write_bytes(
        sign(
            {
                **state,
                "lease_id": second["lease_id"],
                "lease_sha256": hashlib.sha256(_canonical_json(second)).hexdigest(),
                "status": "revoked",
            },
            b"lfl.task-lease-state.v1",
        )
    )
    remaining_claims = authority.discover_for_session(session)
    assert remaining_claims is not None
    assert remaining_claims.lease_id == lease["lease_id"]
    (binding_dir / f"{second['lease_id']}.json").write_text(
        json.dumps(
            {
                "schema": "lfl.task-session-binding/v1",
                "owner_session_id": "other-session",
                "lease_id": second["lease_id"],
            }
        )
    )
    with pytest.raises(TaskAuthorityError, match="authority_binding_invalid"):
        authority.discover_for_session(session)
    binding_dir.chmod(0o777)
    with pytest.raises(TaskAuthorityError, match="authority_bindings_untrusted"):
        authority.discover_for_session(session)


def test_trusted_task_execution_authorize_app_uses_real_signed_exact_cdp_resource(
    tmp_path, signed_receipts, monkeypatch,
):
    import os
    import subprocess

    from llm_loop.core.run_context import current_session_id, current_task_execution
    from llm_loop.tools.task_execution import TaskExecutionError, TrustedTaskExecution

    pem, original, original_state, sign, _request = signed_receipts
    project = tmp_path / "project-a"
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    (project / "file.py").write_text("safe\n")
    subprocess.run(["git", "-C", str(project), "add", "file.py"], check=True)
    subprocess.run(["git", "-C", str(project), "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-qm", "initial"], check=True)
    head = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

    from datetime import UTC, datetime, timedelta
    lease = {
        **original,
        "issued_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        "resources": [
            {"kind": "app", "identity": "lfl.cdp.dedicated", "verbs": ["edit"]}
        ],
    }
    state = {
        **original_state,
        "lease_sha256": hashlib.sha256(_canonical_json(lease)).hexdigest(),
    }
    root = tmp_path / "authority"
    (root / "leases").mkdir(parents=True, mode=0o700)
    (root / "states").mkdir(mode=0o700)
    root.chmod(0o700)
    (root / "leases" / f"{lease['lease_id']}.json").write_bytes(sign(lease, b"lfl.task-lease.v1"))
    (root / "states" / f"{lease['lease_id']}.json").write_bytes(sign(state, b"lfl.task-lease-state.v1"))
    (root / "leases" / f"{lease['lease_id']}.json").chmod(0o600)
    (root / "states" / f"{lease['lease_id']}.json").chmod(0o600)
    monkeypatch.setattr(RootOwnedTaskAuthority, "_trust", lambda self: (os.getuid(), pem))
    authority = RootOwnedTaskAuthority(root)

    lanes_dir = tmp_path / "lanes"
    lanes_dir.mkdir(mode=0o700)
    lane = {
        "status": "active", "goal_id": lease["goal_id"],
        "owner_session_id": lease["owner_session_id"], "version": 2,
        "head_sha": head, "worktree": str(project),
    }
    class Lanes:
        _dir = lanes_dir
        def get(self, _lane_id): return lane

    from typing import Any, cast
    task = TrustedTaskExecution(
        authority=authority, lanes=cast(Any, Lanes()), lease_id=lease["lease_id"],
        goal_id=lease["goal_id"], task_id=lease["task_id"],
        owner_session_id=lease["owner_session_id"], agent_id=lease["agent_id"],
        lane_id=lease["lane_id"], revision=lease["revision"], lane_version=2,
        expected_head=head, protected_roots=(str(root), str(lanes_dir)),
        task_state_validator=lambda: None,
    )
    session_token = current_session_id.set(lease["owner_session_id"])
    task_token = current_task_execution.set(task)
    try:
        task.authorize_app(
            "lfl.cdp.dedicated", verb="edit", os_permission_granted=True,
            backend_supported=True,
        )
        with pytest.raises(TaskExecutionError, match="capability_scope_missing"):
            task.authorize_app(
                "lfl.cdp.other", verb="edit", os_permission_granted=True,
                backend_supported=True,
            )
        with pytest.raises(TaskExecutionError, match="sandbox_backend_unsupported"):
            task.authorize_app(
                "lfl.cdp.dedicated", verb="edit", os_permission_granted=True,
                backend_supported=False,
            )
    finally:
        current_task_execution.reset(task_token)
        current_session_id.reset(session_token)


def test_trusted_service_real_ed25519_lease_lane_cas_parent_and_revocation(
    tmp_path, signed_receipts, monkeypatch,
):
    """Real signed service scope and LaneStore; no fake allow verdict."""
    import subprocess

    from llm_loop.core.run_context import current_session_id, current_task_execution
    from llm_loop.introspection.lane import LaneStore
    from llm_loop.tools.task_execution import TaskExecutionError, TrustedTaskExecution

    pem, original, original_state, sign, _ = signed_receipts
    project = tmp_path / "project-a"
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    (project / "file.py").write_text("safe\n")
    subprocess.run(["git", "-C", str(project), "add", "file.py"], check=True)
    subprocess.run([
        "git", "-C", str(project), "-c", "user.name=test",
        "-c", "user.email=test@example.invalid", "commit", "-qm", "initial",
    ], check=True)
    head = subprocess.run(
        ["git", "-C", str(project), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    lanes = LaneStore(tmp_path / "lanes")
    row = lanes.create(
        branch="feat/test-signed-service", worktree=str(project),
        base_main_sha=head, goal_id=original["goal_id"],
        owner_session_id=original["owner_session_id"], paths=["file.py"],
    )
    lanes.update(row.lane_id, expected_version=1, status="active", head_sha=head)
    lease = {
        **original, "lane_id": row.lane_id,
        "issued_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        "resources": [{"kind": "service", "identity": "web", "verbs": ["restart"]}],
    }
    state = {**original_state, "lease_sha256": hashlib.sha256(_canonical_json(lease)).hexdigest()}
    root = tmp_path / "host-service"
    (root / "leases").mkdir(parents=True, mode=0o700)
    (root / "states").mkdir(mode=0o700)
    root.chmod(0o700)
    monkeypatch.setattr(RootOwnedTaskAuthority, "_trust", lambda self: (os.getuid(), pem))

    def write_receipts(payload, status="active"):
        current = {
            **state, "status": status,
            "lease_sha256": hashlib.sha256(_canonical_json(payload)).hexdigest(),
        }
        for folder, value, domain in (
            ("leases", payload, b"lfl.task-lease.v1"),
            ("states", current, b"lfl.task-lease-state.v1"),
        ):
            path = root / folder / f"{payload['lease_id']}.json"
            path.write_bytes(sign(value, domain))
            path.chmod(0o600)

    write_receipts(lease)
    task = TrustedTaskExecution(
        authority=RootOwnedTaskAuthority(root), lanes=lanes,
        lease_id=lease["lease_id"], goal_id=lease["goal_id"],
        task_id=lease["task_id"], owner_session_id=lease["owner_session_id"],
        agent_id=lease["agent_id"], lane_id=row.lane_id,
        revision=lease["revision"], lane_version=2, expected_head=head,
        protected_roots=(str(root), str(lanes._dir)),
        task_state_validator=lambda: None,
    )
    sid = current_session_id.set(lease["owner_session_id"])
    token = current_task_execution.set(task)
    try:
        task.authorize_service("web", os_permission_granted=True, backend_supported=True)
        with pytest.raises(TaskExecutionError, match="capability_scope_missing"):
            task.authorize_service("feishu", os_permission_granted=True, backend_supported=True)
        with pytest.raises(TaskExecutionError, match="sandbox_backend_unsupported"):
            task.authorize_service("web", os_permission_granted=True, backend_supported=False)
        with pytest.raises(TaskExecutionError, match="os_permission_required"):
            task.authorize_service("web", os_permission_granted=False, backend_supported=True)
        write_receipts(lease, status="revoked")
        with pytest.raises(TaskExecutionError, match="authority_lease_revoked"):
            task.authorize_service("web", os_permission_granted=True, backend_supported=True)
        parented = {**lease, "parent_lease_id": "lease-parent-12345678"}
        write_receipts(parented)
        with pytest.raises(TaskExecutionError, match="task_parent_lease_chain_unverified"):
            task.authorize_service("web", os_permission_granted=True, backend_supported=True)
        write_receipts(lease)
        lanes.update(row.lane_id, expected_version=2, status="verifying")
        with pytest.raises(TaskExecutionError, match="task_lane_cas_conflict"):
            task.authorize_service("web", os_permission_granted=True, backend_supported=True)
    finally:
        current_task_execution.reset(token)
        current_session_id.reset(sid)
