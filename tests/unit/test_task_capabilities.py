"""M1 Task Capability Resolver: authorization is not a model-writable boolean."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from llm_loop.core.task_capabilities import (
    CapabilityRequest,
    CapabilityResource,
    HostAuthorityFacts,
    TaskLeaseClaims,
    resolve_capability,
)


def _fixtures(tmp_path):
    a = (tmp_path / "project-a").resolve()
    b = (tmp_path / "project-b").resolve()
    secret = (a / ".secrets").resolve()
    a.mkdir()
    b.mkdir()
    (a / ".secrets").mkdir()
    lease = TaskLeaseClaims(
        lease_id="lease-1",
        goal_id="goal-1",
        task_id="task-1",
        owner_session_id="owner-1",
        agent_id="agent-1",
        lane_id="lane-1",
        revision=3,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        resources=(
            CapabilityResource(
                "project", str(a), frozenset({"read", "write", "create", "git_commit"})
            ),
            CapabilityResource("project", str(b), frozenset({"read", "write"})),
        ),
    )
    req = CapabilityRequest(
        "goal-1",
        "task-1",
        "owner-1",
        "agent-1",
        "lane-1",
        3,
        "project",
        str(a / "file.txt"),
        "write",
    )
    facts = HostAuthorityFacts(
        authority="verified",
        parent_scope_allows=True,
        lane_fence_valid=True,
        backend_supported=True,
        os_permission_granted=True,
        protected_roots=(str(secret),),
    )
    return a, b, lease, req, facts


def test_two_project_scope_and_unapproved_third(tmp_path):
    a, b, lease, req, facts = _fixtures(tmp_path)
    assert resolve_capability(req, lease=lease, facts=facts).allowed
    second = CapabilityRequest(
        req.goal_id,
        req.task_id,
        req.owner_session_id,
        req.agent_id,
        req.lane_id,
        3,
        "project",
        str(b / "x"),
        "write",
    )
    assert resolve_capability(second, lease=lease, facts=facts).allowed
    third = CapabilityRequest(
        req.goal_id,
        req.task_id,
        req.owner_session_id,
        req.agent_id,
        req.lane_id,
        3,
        "project",
        str(tmp_path / "project-c" / "x"),
        "write",
    )
    denied = resolve_capability(third, lease=lease, facts=facts)
    assert denied.reason_code == "capability_scope_missing"
    assert denied.approval_required


def test_component_boundary_and_symlink_escape(tmp_path):
    a, _b, lease, req, facts = _fixtures(tmp_path)
    neighbor = tmp_path / "project-a-evil"
    neighbor.mkdir()
    denied = CapabilityRequest(
        req.goal_id,
        req.task_id,
        req.owner_session_id,
        req.agent_id,
        req.lane_id,
        3,
        "project",
        str(neighbor / "x"),
        "write",
    )
    assert not resolve_capability(denied, lease=lease, facts=facts).allowed
    link = a / "escape"
    link.symlink_to(neighbor, target_is_directory=True)
    escaped = CapabilityRequest(
        req.goal_id,
        req.task_id,
        req.owner_session_id,
        req.agent_id,
        req.lane_id,
        3,
        "project",
        str(link / "x"),
        "write",
    )
    assert not resolve_capability(escaped, lease=lease, facts=facts).allowed


def test_protected_root_overrides_project_allow(tmp_path):
    a, _b, lease, req, facts = _fixtures(tmp_path)
    secret = CapabilityRequest(
        req.goal_id,
        req.task_id,
        req.owner_session_id,
        req.agent_id,
        req.lane_id,
        3,
        "project",
        str(a / ".secrets" / "key"),
        "read",
    )
    result = resolve_capability(secret, lease=lease, facts=facts)
    assert result.reason_code == "protected_path_denied"
    assert not result.allowed


@pytest.mark.parametrize(
    ("facts_delta", "expected"),
    [
        ({"authority": "missing"}, "capability_scope_missing"),
        ({"authority": "invalid"}, "lease_unverified"),
        ({"authority": "revoked"}, "lease_revoked"),
        ({"parent_scope_allows": False}, "parent_scope_denied"),
        ({"lane_fence_valid": False}, "lane_conflict"),
        ({"backend_supported": False}, "sandbox_backend_unsupported"),
        ({"os_permission_granted": False}, "os_permission_required"),
    ],
)
def test_every_authority_gate_fails_closed(tmp_path, facts_delta, expected):
    _a, _b, lease, req, facts = _fixtures(tmp_path)
    from dataclasses import replace

    facts = replace(facts, **facts_delta)
    result = resolve_capability(req, lease=lease, facts=facts)
    assert not result.allowed
    assert result.reason_code == expected


def test_default_facts_never_allow(tmp_path):
    _a, _b, lease, req, _facts = _fixtures(tmp_path)
    assert not resolve_capability(req, lease=lease, facts=HostAuthorityFacts()).allowed


def test_identity_and_revision_are_bound(tmp_path):
    _a, _b, lease, req, facts = _fixtures(tmp_path)
    from dataclasses import replace

    assert (
        resolve_capability(replace(req, agent_id="other"), lease=lease, facts=facts).reason_code
        == "lease_identity_mismatch"
    )
    assert (
        resolve_capability(replace(req, task_id="other"), lease=lease, facts=facts).reason_code
        == "lease_identity_mismatch"
    )
    assert (
        resolve_capability(replace(req, lane_id="other"), lease=lease, facts=facts).reason_code
        == "lease_identity_mismatch"
    )
    assert (
        resolve_capability(
            replace(req, owner_session_id="other"), lease=lease, facts=facts
        ).reason_code
        == "lease_identity_mismatch"
    )
    assert (
        resolve_capability(replace(req, expected_revision=2), lease=lease, facts=facts).reason_code
        == "lease_revision_stale"
    )


def test_expiry_uses_timezone_aware_clock(tmp_path):
    _a, _b, lease, req, facts = _fixtures(tmp_path)
    assert (
        resolve_capability(req, lease=lease, facts=facts, now=lease.expires_at).reason_code
        == "lease_expired"
    )
    assert (
        resolve_capability(req, lease=lease, facts=facts, now=datetime.now()).reason_code
        == "invalid_clock"
    )


def test_unsupported_git_push_never_authorized(tmp_path):
    _a, _b, lease, req, facts = _fixtures(tmp_path)
    from dataclasses import replace

    result = resolve_capability(replace(req, verb="git_push"), lease=lease, facts=facts)
    assert result.reason_code == "unsupported_capability_verb"


def test_app_and_service_exact_identity(tmp_path):
    _a, _b, lease, req, facts = _fixtures(tmp_path)
    from dataclasses import replace

    lease = replace(
        lease,
        resources=(
            *lease.resources,
            CapabilityResource("app", "com.example.Editor", frozenset({"observe", "edit"})),
            CapabilityResource("service", "lfl-web", frozenset({"status", "restart"})),
        ),
    )
    for kind, identity, verb in (
        ("app", "com.example.Editor", "edit"),
        ("service", "lfl-web", "restart"),
    ):
        request = replace(req, kind=kind, target=identity, verb=verb)
        assert resolve_capability(request, lease=lease, facts=facts).allowed
        assert not resolve_capability(
            replace(request, target=identity + "-evil"), lease=lease, facts=facts
        ).allowed


@pytest.mark.parametrize(
    "bad",
    [
        lambda p: CapabilityResource("project", str(p), frozenset({"git_push"})),
        lambda p: CapabilityResource("project", "/", frozenset({"write"})),
        lambda p: CapabilityResource("app", "com.example.*", frozenset({"edit"})),
        lambda p: CapabilityResource("service", "lfl-web", frozenset({"delete"})),
        lambda p: CapabilityResource("project", "relative/path", frozenset({"write"})),
    ],
)
def test_invalid_grant_resource_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        bad(tmp_path)


def test_missing_lease_cannot_use_verified_fact(tmp_path):
    _a, _b, _lease, req, facts = _fixtures(tmp_path)
    assert (
        resolve_capability(req, lease=None, facts=facts).reason_code == "capability_scope_missing"
    )


def test_project_root_identity_must_be_canonical(tmp_path):
    a = tmp_path / "project-a"
    a.mkdir()
    with pytest.raises(ValueError):
        CapabilityResource("project", os.path.join(str(a), "..", "project-a"), frozenset({"read"}))
