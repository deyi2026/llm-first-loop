"""Host-signed Task Lease activation for an admitted LFL Run.

The model cannot select a lease or inject authority facts. Only an issuer-UID
owned session binding under a root-owned trust anchor may activate a Task.
No binding means legacy execution; a present but invalid binding is HOLD.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from llm_loop.introspection.lane import LaneStore
from llm_loop.tools.task_authority import RootOwnedTaskAuthority, TaskAuthorityError
from llm_loop.tools.task_execution import TrustedTaskExecution

_MAC_AUTHORITY = Path("/Library/Application Support/LFL-HostIssuer/task-authority")
_LINUX_AUTHORITY = Path("/var/lib/lfl-host-issuer/task-authority")


class TaskRuntimeActivationError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _installed_authority_root() -> Path | None:
    system = platform.system()
    if system == "Darwin":
        return _MAC_AUTHORITY
    if system == "Linux":
        return _LINUX_AUTHORITY
    return None


def resolve_task_execution_for_run(
    *,
    session_id: str,
    workspace_root: str,
    data_dir: str,
    authority_root: Path | None = None,
) -> TrustedTaskExecution | None:
    """Resolve one real signed lease after Run lease admission, before tools.

    authority_root is a trusted assembler parameter, never a model/tool
    argument. The production lifecycle passes no override.
    """
    root = authority_root if authority_root is not None else _installed_authority_root()
    if root is None or not root.exists():
        return None
    if not root.is_absolute() or os.path.realpath(root) != str(root):
        raise TaskRuntimeActivationError("task_authority_root_untrusted")
    authority = RootOwnedTaskAuthority(root)
    try:
        claims = authority.discover_for_session(session_id)
    except TaskAuthorityError as exc:
        raise TaskRuntimeActivationError(exc.reason_code) from exc
    if claims is None:
        return None
    if claims.parent_lease_id is not None:
        raise TaskRuntimeActivationError("task_parent_lease_chain_unverified")
    if (
        not workspace_root
        or not os.path.isabs(workspace_root)
        or os.path.realpath(workspace_root) != workspace_root
    ):
        raise TaskRuntimeActivationError("task_workspace_invalid")
    audit = Path(data_dir).expanduser().resolve() / "audit"
    if not audit.is_dir():
        raise TaskRuntimeActivationError("task_lane_audit_unavailable")
    lanes = LaneStore(
        audit,
        lock_strict=True,
        enforce_cross_goal=True,
        repo_root=audit.parent.parent,
    )
    lane = lanes.get(claims.lane_id)
    if (
        not lane
        or lane.get("status") != "active"
        or lane.get("goal_id") != claims.goal_id
        or lane.get("owner_session_id") != session_id
        or lane.get("worktree") != workspace_root
        or type(lane.get("version")) is not int
        or not lane.get("head_sha")
    ):
        raise TaskRuntimeActivationError("task_lane_binding_mismatch")
    if not any(
        resource.kind == "project"
        and resource.identity == workspace_root
        and "write" in resource.verbs
        for resource in claims.resources
    ):
        raise TaskRuntimeActivationError("task_workspace_not_signed")
    # The ledger SHA alone is insufficient: inspect the physical worktree.
    if not os.path.lexists(os.path.join(workspace_root, ".git")):
        raise TaskRuntimeActivationError("task_worktree_git_missing")
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG") if key in os.environ}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
    )
    try:
        head = subprocess.run(
            ["git", "-C", workspace_root, "rev-parse", "--verify", "HEAD"],
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TaskRuntimeActivationError("task_git_head_unavailable") from exc
    if head.returncode != 0 or head.stdout.strip() != lane["head_sha"]:
        raise TaskRuntimeActivationError("task_git_head_cas_conflict")
    return TrustedTaskExecution(
        authority=authority,
        lanes=lanes,
        lease_id=claims.lease_id,
        goal_id=claims.goal_id,
        task_id=claims.task_id,
        owner_session_id=claims.owner_session_id,
        agent_id=claims.agent_id,
        lane_id=claims.lane_id,
        revision=claims.revision,
        lane_version=lane["version"],
        expected_head=lane["head_sha"],
        protected_roots=(str(audit), str(root)),
    )
