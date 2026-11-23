"""Detached Host-side Task service Lease verifier.

The runtime lifecycle kernel invokes this fixed module as a subprocess so the
kernel does not acquire a reverse dependency on the tools/capability plane.
This process reads the durable action and current deployment itself; command
arguments carry only the data directory and opaque action ID.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

# The detached worker is invoked with -I from the exact immutable release
# source path; bootstrap only that release's src tree, never user-site/PYTHONPATH.
# The trusted interpreter's site-packages must remain for signature verification.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from llm_loop.core.run_context import current_session_id, current_task_execution
from llm_loop.runtime.service_control import ManagedServiceDeploymentStore
from llm_loop.tools.task_runtime import resolve_task_execution_for_run


def verify_action(data_dir: str, action_id: str) -> dict[str, Any]:
    """Re-resolve the installed Host Lease and current Goal/Lane before effects."""
    try:
        store = ManagedServiceDeploymentStore(Path(data_dir).expanduser().resolve())
        action = store.read_action(action_id)
        desired = store.read()
        if action is None or desired is None:
            return {"decision": "DENY", "reason": "task_service_action_missing"}
        if (
            not action.task_lease_id
            or action.origin != "task-restart"
            or action.target not in {"web", "feishu", "wecom", "learning"}
            or action.target == "all"
            or action.status not in {"waiting_for_idle", "running"}
            or action.deployment_generation != desired.generation
            or action.deployment_id != desired.deployment_id
        ):
            return {"decision": "DENY", "reason": "task_service_action_binding_invalid"}
        task = resolve_task_execution_for_run(
            session_id=action.task_owner_session_id,
            workspace_root=action.task_worktree,
            data_dir=str(Path(data_dir).expanduser().resolve()),
        )
        if task is None or task.lease_id != action.task_lease_id:
            return {"decision": "DENY", "reason": "task_service_lease_changed"}
        if task.owner_session_id != action.task_owner_session_id:
            return {"decision": "DENY", "reason": "task_service_owner_changed"}
        session_token = current_session_id.set(task.owner_session_id)
        task_token = current_task_execution.set(task)
        try:
            restart_script = Path(desired.runtime_root) / "scripts" / "restart_mirror.sh"
            backend_supported = (
                platform.system() in {"Darwin", "Linux"}
                and restart_script.is_file()
                and os.access(restart_script, os.X_OK)
            )
            os_permission_granted = (
                backend_supported
                and os.access(Path(desired.runtime_root), os.W_OK)
                and os.access(restart_script, os.X_OK)
            )
            task.authorize_service(
                action.target,
                os_permission_granted=os_permission_granted,
                backend_supported=backend_supported,
            )
        finally:
            current_task_execution.reset(task_token)
            current_session_id.reset(session_token)
        return {
            "decision": "PASS",
            "action_id": action.action_id,
            "target": action.target,
            "generation": desired.generation,
        }
    except Exception as exc:  # noqa: BLE001 - every Host/ledger failure denies
        return {
            "decision": "DENY",
            "reason": str(getattr(exc, "reason_code", "task_service_worker_fence_unavailable")),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="llm_loop.tools.task_service_worker")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--action-id", required=True)
    args = parser.parse_args(argv)
    result = verify_action(args.data_dir, args.action_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("decision") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
