"""Host-signed Task Lease: verification, revocation, replay and trust boundaries."""

from __future__ import annotations

import base64
import hashlib
import json
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
