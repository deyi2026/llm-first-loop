"""Offline separated-UID Task Lease issuer: cross-library signatures and denial."""

from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

from llm_loop.core.task_capabilities import CapabilityRequest
from llm_loop.tools.task_authority import TaskAuthorityError, verify_signed_task_lease
from scripts import host_task_lease_issuer as issuer

NOW = datetime(2026, 11, 19, 2, 0, tzinfo=UTC)


def test_mac_task_host_anchor_is_dedicated_and_matches_runtime():
    from llm_loop.tools.task_runtime import _MAC_AUTHORITY

    assert issuer._BASE == _MAC_AUTHORITY
    assert issuer._BASE.parent == Path("/Library/LFL-TaskHostIssuer")
    assert issuer._BASE.parent / "runtime" / "site" == issuer._TRUSTED_SITE
    assert "Application Support" not in str(issuer._BASE)


def test_crypto_import_denies_group_writable_dedicated_ancestor(monkeypatch):
    def fake_lstat(path):
        mode = 0o775 if str(path) == "/Library/LFL-TaskHostIssuer" else 0o755
        return SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=0, st_gid=80)

    with monkeypatch.context() as m:
        m.setattr(Path, "lstat", fake_lstat)
        with pytest.raises(issuer.IssuerHoldError, match="issuer_crypto_runtime_untrusted"):
            issuer._crypto()


@pytest.mark.parametrize(
    ("path", "mode", "uid", "gid", "platform", "allowed"),
    [
        ("/Library", 0o775, 0, 80, "darwin", True),
        ("/Library", 0o755, 0, 0, "darwin", True),
        ("/Library", 0o775, 0, 80, "linux", False),
        ("/Library", 0o775, 0, 20, "darwin", False),
        ("/Library", 0o773, 0, 80, "darwin", False),
        ("/Library", 0o777, 0, 80, "darwin", False),
        ("/Library", 0o775, 501, 80, "darwin", False),
        ("/Library/LFL-TaskHostIssuer", 0o775, 0, 80, "darwin", False),
        ("/", 0o755, 0, 0, "darwin", True),
    ],
)
def test_root_ancestor_exception_is_exact_mac_admin_library(
    monkeypatch, path, mode, uid, gid, platform, allowed
):
    import llm_loop.tools.task_authority as authority

    info = SimpleNamespace(st_mode=stat.S_IFDIR | mode, st_uid=uid, st_gid=gid)
    with monkeypatch.context() as m:
        m.setattr(issuer.sys, "platform", platform)
        assert issuer._trusted_root_ancestor(Path(path), info) is allowed
        assert authority._trusted_root_ancestor(Path(path), info) is allowed


def test_issuer_create_and_revoke_sync_parent_directory(tmp_path, monkeypatch):
    """No SIGNED/REVOKED acknowledgement before the directory entry is durable."""
    actual_fsync = os.fsync
    synced: list[str] = []

    def recorded_fsync(fd):
        synced.append("dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file")
        actual_fsync(fd)

    with monkeypatch.context() as m:
        m.setattr(issuer.os, "fsync", recorded_fsync)
        target = tmp_path / "lease.json"
        issuer._create(target, b"active", 0o600)
        assert synced == ["file", "dir"]
        temp = tmp_path / "revoked.tmp"
        issuer._create(temp, b"revoked", 0o600)
        synced.clear()
        issuer._replace_state_durable(temp, target)
        assert synced == ["dir"]
        assert target.read_bytes() == b"revoked"


def test_revoke_parent_sync_failure_never_reports_success(tmp_path, monkeypatch):
    target, temporary = tmp_path / "lease.json", tmp_path / "revoke.tmp"
    target.write_bytes(b"active")
    temporary.write_bytes(b"revoked")

    def failed_sync(_path):
        raise OSError("directory fsync failed")

    monkeypatch.setattr(issuer, "_sync_parent_directory", failed_sync)
    with pytest.raises(OSError, match="directory fsync failed"):
        issuer._replace_state_durable(temporary, target)


@pytest.fixture
def approval(tmp_path):
    a, b = tmp_path / "project-a", tmp_path / "project-b"
    a.mkdir()
    b.mkdir()
    return {
        "schema": "lfl.task-approval/v1",
        "approval_id": "approval-12345678",
        "approved_at": NOW.isoformat(),
        "approved_by": "operator",
        "purpose": "one bounded two-project task",
        "goal_id": "GOAL-test",
        "task_id": "TASK-test",
        "owner_session_id": "owner-session",
        "agent_id": "agent-1",
        "lane_id": "lane-1",
        "revision": 1,
        "authority_epoch": 3,
        "ttl_seconds": 3600,
        "parent_lease_id": None,
        "resources": [
            {"kind": "project", "identity": str(a), "verbs": ["read", "write"]},
            {"kind": "project", "identity": str(b), "verbs": ["read", "write", "git_commit"]},
        ],
    }


def _request(approval):
    return CapabilityRequest(
        approval["goal_id"],
        approval["task_id"],
        approval["owner_session_id"],
        approval["agent_id"],
        approval["lane_id"],
        approval["revision"],
        "project",
        approval["resources"][1]["identity"],
        "write",
    )


def test_separate_uid_issuer_cross_crypto_valid_and_revoke(approval):
    key = ECC.generate(curve="Ed25519")
    lease, state, lease_id = issuer.issue_receipts(
        approval,
        key,
        eddsa,
        now=NOW,
        lease_id="lease-12345678",
    )
    public = key.public_key().export_key(format="PEM").encode()
    req = _request(approval)
    claims = verify_signed_task_lease(public, lease, state, req, now=NOW)
    assert claims.lease_id == lease_id
    assert len(claims.resources) == 2
    revoked, ident = issuer.revoked_state(lease, key, eddsa)
    assert ident == lease_id
    with pytest.raises(TaskAuthorityError, match="authority_lease_revoked"):
        verify_signed_task_lease(public, lease, revoked, req, now=NOW)


def test_invalid_approval_scope_ttl_and_staleness_rejected(approval):
    key = ECC.generate(curve="Ed25519")
    variants = [
        {**approval, "ttl_seconds": 86401},
        {**approval, "approved_at": (NOW - timedelta(minutes=11)).isoformat()},
        {**approval, "resources": [{"kind": "project", "identity": "/", "verbs": ["write"]}]},
        {**approval, "resources": [{"kind": "service", "identity": "*", "verbs": ["restart"]}]},
        {**approval, "allow_all_shell": True},
        {**approval, "revision": True},
        {**approval, "parent_lease_id": "lease-parent123"},
    ]
    for invalid in variants:
        with pytest.raises(issuer.IssuerHoldError):
            issuer.issue_receipts(invalid, key, eddsa, now=NOW)


def test_wrong_key_cannot_revoke_lease(approval):
    key = ECC.generate(curve="Ed25519")
    lease, _state, _ = issuer.issue_receipts(approval, key, eddsa, now=NOW)
    with pytest.raises(issuer.IssuerHoldError, match="lease_receipt_signature_invalid"):
        issuer.revoked_state(lease, ECC.generate(curve="Ed25519"), eddsa)


def test_tampered_signed_lease_rejected_by_runtime(approval):
    key = ECC.generate(curve="Ed25519")
    lease, state, _ = issuer.issue_receipts(approval, key, eddsa, now=NOW)
    forged = json.loads(lease)
    forged["payload"]["resources"][0]["verbs"].append("delete")
    public = key.public_key().export_key(format="PEM").encode()
    with pytest.raises(TaskAuthorityError, match="authority_signature_invalid"):
        verify_signed_task_lease(
            public,
            json.dumps(forged).encode(),
            state,
            _request(approval),
            now=NOW,
        )


def test_unprivileged_cli_fails_closed_without_side_effects(capsys):
    code = issuer.main(["--mode", "keygen"])
    result = json.loads(capsys.readouterr().out)
    assert code == 1
    assert result["decision"] == "HOLD"
    assert result["reason"] == "issuer_uid_invalid"
