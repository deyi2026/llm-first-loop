"""Trusted per-run task sandbox execution context (never a tool argument).

The Host/runtime injects this object into a ContextVar only after obtaining a
signed lease from a root-owned authority. A model cannot supply project roots,
authority facts, signatures or the Lane CAS as execute_command arguments.
Every process spawn re-verifies the signed state and physical sandbox plan.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

from llm_loop.core.run_context import (
    current_session_id,
    current_task_execution,
    current_write_scope,
    workspace_base,
)
from llm_loop.core.task_capabilities import (
    CapabilityRequest,
    HostAuthorityFacts,
    resolve_capability,
)
from llm_loop.core.write_scope import scope_allows
from llm_loop.introspection.lane import LaneStore
from llm_loop.tools.task_authority import RootOwnedTaskAuthority, TaskAuthorityError
from llm_loop.tools.task_sandbox import TaskSandboxPlan, compile_task_sandbox


class TaskExecutionError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _task_git_env(keys: tuple[str, ...] = ("PATH", "HOME", "LANG")) -> dict[str, str]:
    """Read only non-secret Git subprocess keys via the existing config boundary."""
    from llm_loop.config import _raw_env

    values = {key: _raw_env(key, preserve_raw=True) for key in keys}
    return {key: value for key, value in values.items() if value}


@dataclass(frozen=True)
class TrustedTaskExecution:
    authority: RootOwnedTaskAuthority
    lanes: LaneStore
    lease_id: str
    goal_id: str
    task_id: str
    owner_session_id: str
    agent_id: str
    lane_id: str
    revision: int
    lane_version: int
    expected_head: str
    protected_roots: tuple[str, ...]
    task_state_validator: Callable[[], None]
    _git_cas: tuple[int, str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_git_cas", (self.lane_version, self.expected_head))

    @property
    def git_cas(self) -> tuple[int, str]:
        """One immutable CAS snapshot shared by copied tool contexts in this Run."""
        return self._git_cas

    def _advance_git_cas(
        self, previous: tuple[int, str], *, new_version: int, new_head: str,
    ) -> None:
        """Advance only from this Run's successful managed Git receipt.

        Never refresh from an arbitrary Lane or Git HEAD. The adapter serializes
        commits and updates the Lane with CAS before returning its receipt. A
        single tuple replacement preserves the pair across copied ContextVars.
        Signed identity, resources and revision remain frozen.
        """
        if (
            current_task_execution.get() is not self
            or current_session_id.get() != self.owner_session_id
            or self._git_cas != previous
            or new_version != previous[0] + 1
            or new_head == previous[1]
            or len(new_head) != 40
            or any(char not in "0123456789abcdef" for char in new_head)
        ):
            raise TaskExecutionError("git_effect_committed_context_sync_failed")
        object.__setattr__(self, "_git_cas", (new_version, new_head))

    def authorize_app(
        self,
        bundle_id: str,
        *,
        verb: str = "edit",
        os_permission_granted: bool,
        backend_supported: bool,
    ) -> None:
        """Reverify exact Host-signed app scope before native AX delivery.

        The bundle identity must be observed by the desktop backend, never
        copied from a model parameter. This does not override the desktop
        privacy, foreground, TCC, review, confirmation or write gates.
        """
        if (
            current_task_execution.get() is not self
            or current_session_id.get() != self.owner_session_id
            or verb not in ("observe", "edit")
            or not isinstance(bundle_id, str)
            or not bundle_id.strip()
            or any(char in bundle_id for char in ("/", "\\", "*"))
        ):
            raise TaskExecutionError("task_app_identity_invalid")
        self.task_state_validator()
        if verb == "edit":
            parent_scope = current_write_scope.get()
            if parent_scope is not None and parent_scope.declared:
                raise TaskExecutionError("task_parent_scope_requires_precise_compilation")
        git_cas = self.git_cas
        lane = self.lanes.get(self.lane_id)
        if (
            not lane
            or lane.get("status") != "active"
            or lane.get("goal_id") != self.goal_id
            or lane.get("owner_session_id") != self.owner_session_id
            or (lane.get("version"), lane.get("head_sha")) != git_cas
        ):
            raise TaskExecutionError("task_lane_cas_conflict")
        worktree = os.path.realpath(str(lane.get("worktree") or ""))
        if not os.path.lexists(os.path.join(worktree, ".git")):
            raise TaskExecutionError("task_worktree_git_missing")
        env = _task_git_env()
        env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_NO_REPLACE_OBJECTS="1",
        )
        try:
            observed = subprocess.run(
                ["git", "-C", worktree, "rev-parse", "--verify", "HEAD"],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TaskExecutionError("task_git_head_unavailable") from exc
        if observed.returncode != 0 or observed.stdout.strip() != git_cas[1]:
            raise TaskExecutionError("task_git_head_cas_conflict")
        protected = tuple(os.path.realpath(p) for p in self.protected_roots)
        if (
            os.path.realpath(str(self.authority.root)) not in protected
            or os.path.realpath(str(self.lanes._dir)) not in protected
        ):
            raise TaskExecutionError("task_protected_roots_missing")
        request = CapabilityRequest(
            self.goal_id,
            self.task_id,
            self.owner_session_id,
            self.agent_id,
            self.lane_id,
            self.revision,
            "app",
            bundle_id,
            verb,
        )
        try:
            claims = self.authority.verify(self.lease_id, request)
        except TaskAuthorityError as exc:
            raise TaskExecutionError(exc.reason_code) from exc
        if claims.parent_lease_id is not None:
            raise TaskExecutionError("task_parent_lease_chain_unverified")
        verdict = resolve_capability(
            request,
            lease=claims,
            facts=HostAuthorityFacts(
                authority="verified",
                parent_scope_allows=True,
                lane_fence_valid=True,
                backend_supported=bool(backend_supported),
                os_permission_granted=bool(os_permission_granted),
                protected_roots=protected,
            ),
        )
        if not verdict.allowed:
            raise TaskExecutionError(
                "task_os_tcc_required"
                if verdict.reason_code == "os_permission_required"
                else verdict.reason_code
            )

    def authorize_service(
        self, service: str, *, os_permission_granted: bool, backend_supported: bool,
    ) -> None:
        """Verify exact Host-signed service.restart, Goal/Task and Lane CAS.

        A successful admission is NOT authority for a detached worker. The
        durable action carries this exact Lease ID and the worker re-resolves
        and re-verifies it immediately before the physical restart script.
        """
        if (
            current_task_execution.get() is not self
            or current_session_id.get() != self.owner_session_id
            or service not in ("web", "feishu", "wecom", "learning")
        ):
            raise TaskExecutionError("task_service_identity_invalid")
        self.task_state_validator()
        parent_scope = current_write_scope.get()
        if parent_scope is not None and parent_scope.declared:
            raise TaskExecutionError("task_parent_scope_requires_precise_compilation")
        git_cas = self.git_cas
        lane = self.lanes.get(self.lane_id)
        if (
            not lane
            or lane.get("status") != "active"
            or lane.get("goal_id") != self.goal_id
            or lane.get("owner_session_id") != self.owner_session_id
            or (lane.get("version"), lane.get("head_sha")) != git_cas
        ):
            raise TaskExecutionError("task_lane_cas_conflict")
        worktree = os.path.realpath(str(lane.get("worktree") or ""))
        if not os.path.lexists(os.path.join(worktree, ".git")):
            raise TaskExecutionError("task_worktree_git_missing")
        env = _task_git_env()
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_REPLACE_OBJECTS="1")
        try:
            observed = subprocess.run(
                ["git", "-C", worktree, "rev-parse", "--verify", "HEAD"],
                env=env, capture_output=True, text=True, timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TaskExecutionError("task_git_head_unavailable") from exc
        if observed.returncode != 0 or observed.stdout.strip() != git_cas[1]:
            raise TaskExecutionError("task_git_head_cas_conflict")
        protected = tuple(os.path.realpath(path) for path in self.protected_roots)
        if (
            os.path.realpath(str(self.authority.root)) not in protected
            or os.path.realpath(str(self.lanes._dir)) not in protected
        ):
            raise TaskExecutionError("task_protected_roots_missing")
        request = CapabilityRequest(
            self.goal_id, self.task_id, self.owner_session_id, self.agent_id,
            self.lane_id, self.revision, "service", service, "restart",
        )
        try:
            claims = self.authority.verify(self.lease_id, request)
        except TaskAuthorityError as exc:
            raise TaskExecutionError(exc.reason_code) from exc
        if claims.parent_lease_id is not None:
            raise TaskExecutionError("task_parent_lease_chain_unverified")
        verdict = resolve_capability(
            request, lease=claims,
            facts=HostAuthorityFacts(
                authority="verified", parent_scope_allows=True,
                lane_fence_valid=True, backend_supported=bool(backend_supported),
                os_permission_granted=bool(os_permission_granted),
                protected_roots=protected,
            ),
        )
        if not verdict.allowed:
            raise TaskExecutionError(verdict.reason_code)

    def authorize_file(self, target: str, verb: str) -> str:
        """Authorize an exact cross-project file path; return its signed root.

        FileService must still perform its own atomic write/CAS and durable
        effect journal. This check is repeated at its mutation boundary.
        """
        if (
            current_task_execution.get() is not self
            or current_session_id.get() != self.owner_session_id
            or verb not in ("read", "write", "create", "rename", "delete")
            or not os.path.isabs(target)
            or os.path.realpath(target) != target
        ):
            raise TaskExecutionError("task_file_identity_or_path_invalid")
        self.task_state_validator()
        git_cas = self.git_cas
        lane = self.lanes.get(self.lane_id)
        if (
            not lane
            or lane.get("status") != "active"
            or lane.get("goal_id") != self.goal_id
            or lane.get("owner_session_id") != self.owner_session_id
            or (lane.get("version"), lane.get("head_sha")) != git_cas
        ):
            raise TaskExecutionError("task_lane_cas_conflict")
        worktree = os.path.realpath(str(lane.get("worktree") or ""))
        if os.path.lexists(os.path.join(worktree, ".git")):
            env = _task_git_env(("PATH", "HOME"))
            env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
            try:
                observed = subprocess.run(
                    ["git", "-C", worktree, "rev-parse", "--verify", "HEAD"],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise TaskExecutionError("task_git_head_unavailable") from exc
            if observed.returncode != 0 or observed.stdout.strip() != git_cas[1]:
                raise TaskExecutionError("task_git_head_cas_conflict")
        for other in self.lanes.list():
            if other.get("lane_id") == self.lane_id or not other.get("worktree"):
                continue
            other_root = os.path.realpath(str(other["worktree"]))
            if os.path.commonpath((target, other_root)) == other_root:
                raise TaskExecutionError("task_other_lane_worktree_conflict")
        parent_scope = current_write_scope.get()
        if verb != "read" and parent_scope is not None:
            allowed, _reason = scope_allows(parent_scope, target, workspace_base())
            if not allowed:
                raise TaskExecutionError("task_parent_scope_denied")
        protected = tuple(os.path.realpath(p) for p in self.protected_roots)
        if (
            os.path.realpath(str(self.authority.root)) not in protected
            or os.path.realpath(str(self.lanes._dir)) not in protected
        ):
            raise TaskExecutionError("task_protected_roots_missing")
        request = CapabilityRequest(
            self.goal_id,
            self.task_id,
            self.owner_session_id,
            self.agent_id,
            self.lane_id,
            self.revision,
            "project",
            target,
            verb,
        )
        try:
            claims = self.authority.verify(self.lease_id, request)
        except TaskAuthorityError as exc:
            raise TaskExecutionError(exc.reason_code) from exc
        if claims.parent_lease_id is not None:
            raise TaskExecutionError("task_parent_lease_chain_unverified")
        roots = [
            resource.identity
            for resource in claims.resources
            if resource.kind == "project"
            and verb in resource.verbs
            and (
                target == resource.identity
                or target.startswith(resource.identity.rstrip("/") + "/")
            )
        ]
        if not roots:
            raise TaskExecutionError("task_file_root_not_authorized")
        root = max(roots, key=len)
        facts = HostAuthorityFacts(
            authority="verified",
            parent_scope_allows=True,
            lane_fence_valid=True,
            backend_supported=True,
            os_permission_granted=os.access(
                target if verb == "read" else os.path.dirname(target),
                os.R_OK if verb == "read" else os.W_OK,
            ),
            protected_roots=protected,
        )
        verdict = resolve_capability(request, lease=claims, facts=facts)
        if not verdict.allowed:
            raise TaskExecutionError(verdict.reason_code)
        return root

    def _deny_other_lane_roots(self, roots: tuple[str, ...]) -> None:
        """A signed project grant never transfers another active Lane's tree."""
        for other in self.lanes.list():
            if other.get("lane_id") == self.lane_id or not other.get("worktree"):
                continue
            other_root = os.path.realpath(str(other["worktree"]))
            for root in roots:
                try:
                    overlap = os.path.commonpath((root, other_root)) in (root, other_root)
                except (OSError, ValueError):
                    overlap = True
                if overlap:
                    raise TaskExecutionError("task_other_lane_worktree_conflict")

    def preflight(self, command: str, workdir: str, mode: str) -> TaskSandboxPlan:
        """Verify signed lease, parent/Lane/OS facts and compile exact multi-root plan."""
        if current_task_execution.get() is not self:
            raise TaskExecutionError("task_context_not_active")
        self.task_state_validator()
        if current_session_id.get() != self.owner_session_id:
            raise TaskExecutionError("task_owner_session_mismatch")
        parent_scope = current_write_scope.get()
        if parent_scope is not None and parent_scope.declared:
            # A whole writable directory bind would silently widen a narrower
            # per-file child scope. Refuse until exact scope-root compilation.
            raise TaskExecutionError("task_parent_scope_requires_precise_compilation")
        if not os.path.isabs(workdir) or os.path.realpath(workdir) != workdir:
            raise TaskExecutionError("task_workdir_not_canonical")
        git_cas = self.git_cas
        lane = self.lanes.get(self.lane_id)
        if (
            not lane
            or lane.get("status") != "active"
            or lane.get("goal_id") != self.goal_id
            or lane.get("owner_session_id") != self.owner_session_id
            or (lane.get("version"), lane.get("head_sha")) != git_cas
            or os.path.realpath(str(lane.get("worktree") or "")) != workdir
        ):
            raise TaskExecutionError("task_lane_cas_conflict")
        protected = tuple(os.path.realpath(p) for p in self.protected_roots)
        if (
            not protected
            or os.path.realpath(str(self.authority.root)) not in protected
            or os.path.realpath(str(self.lanes._dir)) not in protected
        ):
            raise TaskExecutionError("task_protected_roots_missing")
        request = CapabilityRequest(
            self.goal_id,
            self.task_id,
            self.owner_session_id,
            self.agent_id,
            self.lane_id,
            self.revision,
            "project",
            workdir,
            "write",
        )
        try:
            claims = self.authority.verify(self.lease_id, request)
        except TaskAuthorityError as exc:
            raise TaskExecutionError(exc.reason_code) from exc
        if claims.parent_lease_id is not None:
            # Until recursive parent-chain verification is wired, never treat
            # an unchecked parent as an implicit all-access grant.
            raise TaskExecutionError("task_parent_lease_chain_unverified")
        roots = tuple(
            resource.identity
            for resource in claims.resources
            if resource.kind == "project" and "write" in resource.verbs
        )
        if workdir not in roots:
            raise TaskExecutionError("task_workdir_not_authorized")
        self._deny_other_lane_roots(roots)
        if os.path.lexists(os.path.join(workdir, ".git")):
            # Compare actual HEAD, not just the potentially stale Lane ledger.
            env = _task_git_env()
            env.update(
                GIT_CONFIG_NOSYSTEM="1",
                GIT_CONFIG_GLOBAL=os.devnull,
                GIT_NO_REPLACE_OBJECTS="1",
            )
            try:
                observed = subprocess.run(
                    ["git", "-C", workdir, "rev-parse", "--verify", "HEAD"],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise TaskExecutionError("task_git_head_unavailable") from exc
            if observed.returncode != 0 or observed.stdout.strip() != git_cas[1]:
                raise TaskExecutionError("task_git_head_cas_conflict")
        for root in roots:
            root_request = CapabilityRequest(
                self.goal_id,
                self.task_id,
                self.owner_session_id,
                self.agent_id,
                self.lane_id,
                self.revision,
                "project",
                root,
                "write",
            )
            facts = HostAuthorityFacts(
                authority="verified",
                parent_scope_allows=True,
                lane_fence_valid=True,
                backend_supported=True,
                os_permission_granted=os.path.isdir(root) and os.access(root, os.W_OK),
                protected_roots=protected,
            )
            verdict = resolve_capability(root_request, lease=claims, facts=facts)
            if not verdict.allowed:
                raise TaskExecutionError(verdict.reason_code)
        try:
            return compile_task_sandbox(
                command,
                workdir,
                verified_project_roots=roots,
                protected_audit_roots=protected,
                mode=mode,
            )
        except (RuntimeError, ValueError) as exc:
            raise TaskExecutionError("task_sandbox_backend_or_roots_unsupported") from exc

    def recheck(self, command: str, workdir: str, mode: str, original: TaskSandboxPlan) -> None:
        """Mutation-boundary re-verification, including revocation and Lane CAS."""
        current = self.preflight(command, workdir, mode)
        if current != original:
            raise TaskExecutionError("task_sandbox_plan_changed")
