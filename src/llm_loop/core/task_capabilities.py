"""Task-scoped capability *decision* contract (M1 foundation).

This module deliberately DOES NOT issue, verify, persist, or expand grants.
A caller must obtain lease claims and all authority facts from a trusted Host
authority, not from model-provided tool arguments. No runtime tool is wired to
this evaluator yet; a positive decision is not proof of OS/backend readiness
or of a completed side effect.

Security invariants:
- fail closed on unknown verbs, resource kinds, identities and authority state;
- exact project-root containment (never lexical prefix), app/service identity;
- a child's allowed set cannot exceed the trusted parent and Lane authority;
- protected roots win over project grants;
- a lease cannot authorize git_push, merge, release or arbitrary shell.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from llm_loop.timekeeping import system_local_now

ResourceKind = Literal["project", "app", "service"]
Decision = Literal["allow", "need_approval", "need_os_permission", "unsupported", "deny", "stale"]
AuthorityStatus = Literal["verified", "missing", "invalid", "revoked"]

_PROJECT_VERBS = frozenset({"read", "write", "create", "rename", "delete", "build", "git_commit"})
_APP_VERBS = frozenset({"observe", "edit"})
_SERVICE_VERBS = frozenset({"status", "restart"})
_VERBS = {
    "project": _PROJECT_VERBS,
    "app": _APP_VERBS,
    "service": _SERVICE_VERBS,
}


def _norm_path(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def _is_within(path: str, root: str) -> bool:
    """Component-safe containment; no prefix matching or cross-drive leaks."""
    try:
        target, base = _norm_path(path), _norm_path(root)
        # Keep component comparisons case-sensitive even on macOS: APFS may
        # use a case-sensitive volume. False denial is safer than treating
        # two distinct roots as one grant.
        return os.path.commonpath((target, base)) == base
    except (ValueError, OSError):
        return False


@dataclass(frozen=True)
class CapabilityResource:
    """Claims from a trusted Host-issued lease; NOT a model request."""

    kind: ResourceKind
    identity: str
    verbs: frozenset[str]

    def __post_init__(self) -> None:
        if self.kind not in _VERBS:
            raise ValueError("unsupported resource kind")
        if not self.identity or not self.verbs or not self.verbs.issubset(_VERBS[self.kind]):
            raise ValueError("invalid resource identity or verbs")
        if self.kind == "project":
            if not os.path.isabs(self.identity) or _norm_path(self.identity) != self.identity:
                raise ValueError("project root must be canonical absolute path")
            if self.identity in (os.sep, _norm_path(os.path.expanduser("~"))):
                raise ValueError("filesystem/home root is not a project scope")
        elif "/" in self.identity or "\\" in self.identity or "*" in self.identity:
            raise ValueError("app/service identity must be exact, not a path or glob")


@dataclass(frozen=True)
class TaskLeaseClaims:
    """Unsigned claims shape. Host signature verification is OUTSIDE this module."""

    lease_id: str
    goal_id: str
    task_id: str
    owner_session_id: str
    agent_id: str
    lane_id: str
    revision: int
    expires_at: datetime
    resources: tuple[CapabilityResource, ...]
    parent_lease_id: str | None = None

    def __post_init__(self) -> None:
        if not all(
            (
                self.lease_id,
                self.goal_id,
                self.task_id,
                self.owner_session_id,
                self.agent_id,
                self.lane_id,
            )
        ):
            raise ValueError("lease identity is required")
        if type(self.revision) is not int or self.revision < 1:
            raise ValueError("lease revision must be positive")
        if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
            raise ValueError("lease expiry must be timezone-aware")
        if not self.resources:
            raise ValueError("lease must have an explicit resource scope")


@dataclass(frozen=True)
class CapabilityRequest:
    goal_id: str
    task_id: str
    owner_session_id: str
    agent_id: str
    lane_id: str
    expected_revision: int
    kind: ResourceKind
    target: str
    verb: str


@dataclass(frozen=True)
class HostAuthorityFacts:
    """Only a trusted Host assembler may supply these booleans.

    Defaults DENY. Model text, webpage content, tool output and workspace
    files must never be used to set verified/parent/lane/OS/backend facts.
    """

    authority: AuthorityStatus = "missing"
    parent_scope_allows: bool = False
    lane_fence_valid: bool = False
    backend_supported: bool = False
    os_permission_granted: bool = False
    protected_roots: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityVerdict:
    decision: Decision
    layer: str
    reason_code: str
    remediation: str
    approval_required: bool = False
    retryable: bool = False

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"


def _deny(
    decision: Decision,
    layer: str,
    reason: str,
    remediation: str,
    *,
    approval: bool = False,
    retry: bool = False,
) -> CapabilityVerdict:
    return CapabilityVerdict(decision, layer, reason, remediation, approval, retry)


def resolve_capability(
    request: CapabilityRequest,
    *,
    lease: TaskLeaseClaims | None,
    facts: HostAuthorityFacts,
    now: datetime | None = None,
) -> CapabilityVerdict:
    """Pure, conservative preflight. Must be rechecked at the effect boundary.

    The caller MUST verify the Host signature and revocation epoch before
    setting facts.authority='verified'. No tool should expose facts to the
    model as a writable argument. A positive verdict is not a capability
    token and cannot bypass sandbox, OS ACL, TCC, Reviewer or service gates.
    """
    if facts.authority == "revoked":
        return _deny("deny", "owner", "lease_revoked", "重新取得可信 Owner 授权")
    if facts.authority == "invalid":
        return _deny("deny", "owner", "lease_unverified", "Host 验签失败；停止执行")
    if lease is None or facts.authority != "verified":
        return _deny(
            "need_approval",
            "owner",
            "capability_scope_missing",
            "通过可信 Owner 入口申请任务范围",
            approval=True,
        )
    clock = now or system_local_now()
    if clock.tzinfo is None or clock.utcoffset() is None:
        return _deny("deny", "owner", "invalid_clock", "使用可信时区时间重新预检")
    if clock >= lease.expires_at:
        return _deny(
            "need_approval",
            "owner",
            "lease_expired",
            "重新取得任务授权",
            approval=True,
        )
    if (
        request.goal_id != lease.goal_id
        or request.task_id != lease.task_id
        or request.owner_session_id != lease.owner_session_id
        or request.agent_id != lease.agent_id
        or request.lane_id != lease.lane_id
    ):
        return _deny("deny", "owner", "lease_identity_mismatch", "核对可信会话和 Agent 归属")
    if request.expected_revision != lease.revision:
        return _deny("stale", "owner", "lease_revision_stale", "刷新最新授权版本", retry=True)
    if request.kind not in _VERBS or request.verb not in _VERBS[request.kind]:
        return _deny("deny", "owner", "unsupported_capability_verb", "使用已定义的受管操作")
    if not request.target:
        return _deny("deny", "owner", "invalid_resource_identity", "提供真实资源标识")
    if request.kind == "project":
        if not os.path.isabs(request.target):
            return _deny("deny", "owner", "invalid_resource_identity", "使用绝对路径")
        if any(_is_within(request.target, root) for root in facts.protected_roots):
            return _deny("deny", "owner", "protected_path_denied", "受保护路径不允许任务授权")
    covered = any(
        r.kind == request.kind
        and request.verb in r.verbs
        and (
            _is_within(request.target, r.identity)
            if request.kind == "project"
            else request.target == r.identity
        )
        for r in lease.resources
    )
    if not covered:
        return _deny(
            "need_approval",
            "owner",
            "capability_scope_missing",
            "申请增加目标资源或操作动词",
            approval=True,
        )
    if not facts.parent_scope_allows:
        return _deny("deny", "parent_scope", "parent_scope_denied", "由 Owner 扩大父任务范围")
    if not facts.lane_fence_valid:
        return _deny("stale", "lane", "lane_conflict", "协调 Lane 所有权并刷新 CAS", retry=True)
    if not facts.backend_supported:
        return _deny("unsupported", "sandbox", "sandbox_backend_unsupported", "切换已验收执行器")
    if not facts.os_permission_granted:
        return _deny(
            "need_os_permission",
            "os",
            "os_permission_required",
            "完成真实 TCC/Polkit/OS ACL 授权并复核",
        )
    return CapabilityVerdict("allow", "runtime", "capability_ready", "执行器仍需副作用前复检")
