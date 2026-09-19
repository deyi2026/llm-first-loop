"""ProjectCoordinator: bind the FleetStore lease lifecycle to run boundaries.

This is the runtime adapter from DESIGN-20260919-fleet-minimal-slice step 4:

- ``begin_run``  - at a run boundary.  Creates the per-run workspace on first
  sight (deterministic ``<physical_root>/runs/<run_key>`` identity), then
  acquires the lease.  A crashed predecessor is superseded only when its
  lease has actually expired (time-licensed takeover, generation CAS);
  a live unexpired or expiry-free lease fails closed with the precise
  remaining window -- live takeover then needs ``force_reclaim_run``
  (operator action with recorded justification).
- ``run_fact``   - fenced append during the run.
- ``finish_run`` - exactly-once settlement at a real terminal.
- ``reclaim_run``/``reclaim_run_if_expired``/``force_reclaim_run``/``recover``
  - recovery surface for the next coordinator.

The program keeps mechanical facts only (identity, generation, fencing,
exactly-once).  Live-lease takeover authority is expiry or a recorded
operator ``force_reclaim``; the model may propose a takeover, never decide
one.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from llm_loop.fleet.store import (
    ExecutionWorkspace,
    FleetStore,
    LeaseActiveError,
    SettlementError,
    SettlementRecord,
    WorkerLease,
)


class ProjectCoordinator:
    def __init__(
        self,
        *,
        fleet_dir: str | Path,
        project_id: str,
        physical_root: str,
        repo_head: str,
        owner_id: str,
    ) -> None:
        self.store = FleetStore(fleet_dir)
        self.project_id = project_id
        self.physical_root = str(Path(physical_root))
        self.repo_head = repo_head
        self.owner_id = owner_id
        # fused find-or-create: concurrent coordinator boot cannot lose the
        # project-creation race (a plain get->create TOCTOU crashed the loser)
        self.store.get_or_create_project(project_id)

    # ------------------------------------------------------------ identity

    def run_root(self, run_key: str) -> str:
        """Deterministic per-run workspace physical root (run_key is the identity)."""
        return f"{self.physical_root}/runs/{run_key}"

    def _workspace_for(self, run_key: str) -> ExecutionWorkspace:
        run_root = self.run_root(run_key)
        return self.store.get_or_create_workspace(
            self.project_id, run_root, self.repo_head
        )

    def _existing_workspace(self, run_key: str) -> ExecutionWorkspace:
        """Read-only workspace lookup; unknown run_key fails honestly."""
        workspace = self.store.find_workspace(self.project_id, self.run_root(run_key))
        if workspace is None:
            raise KeyError(f"unknown run workspace: {run_key}")
        return workspace

    # -------------------------------------------------------- run boundary

    def begin_run(
        self,
        run_key: str,
        *,
        worker_id: str | None = None,
        ttl_seconds: float | None = None,
    ) -> WorkerLease:
        workspace = self._workspace_for(run_key)
        try:
            current = self.store.current_lease(workspace.workspace_id)
        except KeyError:
            current = None
        if current is not None and current.state == "settled":
            raise SettlementError(
                f"run workspace already settled: {workspace.workspace_id} ({run_key})"
            )
        if current is not None and current.state == "active":
            # Reclaim Authority Gate: a live lease is superseded only by (a)
            # expiry -- time-licensed, CAS on the observed generation so
            # concurrent recoveries have exactly one winner -- or (b) an
            # operator force_reclaim_run with recorded justification.  An
            # unexpired or expiry-free lease fails closed with the precise
            # blocking window; the runner turns this into a typed refusal,
            # never a silent takeover of a worker that may still be alive.
            expires_at = current.expires_at
            if expires_at is not None and time.time() >= expires_at:
                return self.store.reclaim_if_expired(
                    self.project_id,
                    workspace.workspace_id,
                    self.owner_id,
                    ttl_seconds=ttl_seconds,
                    expected_generation=current.generation,
                )
            remaining = None if expires_at is None else expires_at - time.time()
            message = (
                f"run {run_key} ({workspace.workspace_id}) holds an active "
                f"unexpired lease {current.lease_id} (generation "
                f"{current.generation}, remaining {remaining:.3f}s); automatic "
                "resume is fail-closed until expiry, or an operator "
                "force_reclaim_run with the exact lease identity"
                if remaining is not None
                else f"run {run_key} ({workspace.workspace_id}) holds an "
                f"expiry-free active lease {current.lease_id} (generation "
                f"{current.generation}); automatic resume is fail-closed; an "
                "operator force_reclaim_run with the exact lease identity is "
                "required"
            )
            raise LeaseActiveError(message, remaining_seconds=remaining)
        return self.store.acquire_lease(
            self.project_id,
            workspace.workspace_id,
            self.owner_id,
            worker_id=worker_id,
            ttl_seconds=ttl_seconds,
        )

    def run_fact(self, lease: WorkerLease, fact: dict[str, Any]) -> None:
        self.store.record_fact(lease, fact)

    def finish_run(self, lease: WorkerLease, result: dict[str, Any]) -> SettlementRecord:
        return self.store.settle(lease, result)

    def renew_run(self, lease: WorkerLease, *, extend_seconds: float) -> WorkerLease:
        return self.store.renew_lease(lease, extend_seconds=extend_seconds)

    # ------------------------------------------------------------- recovery

    def reclaim_run(
        self,
        workspace_id: str,
        *,
        expected_generation: int | None = None,
        ttl_seconds: float | None = None,
    ) -> WorkerLease:
        return self.store.reclaim(
            self.project_id,
            workspace_id,
            self.owner_id,
            expected_generation=expected_generation,
            ttl_seconds=ttl_seconds,
        )

    def reclaim_run_if_expired(
        self, run_key: str, *, ttl_seconds: float | None = None
    ) -> WorkerLease:
        """Time-licensed takeover of a run past its declared lease expiry."""
        workspace = self._existing_workspace(run_key)
        return self.store.reclaim_if_expired(
            self.project_id, workspace.workspace_id, self.owner_id,
            ttl_seconds=ttl_seconds,
        )

    def force_reclaim_run(
        self,
        run_key: str,
        *,
        expected_lease_id: str,
        expected_generation: int,
        reason: str,
        authorized_by: str,
        ttl_seconds: float | None = None,
    ) -> WorkerLease:
        """Operator-authorized live takeover; the only unexpired takeover path.

        Requires the exact observed lease identity (lease id + generation,
        double CAS), a non-empty justification and an authorizer id; the
        store records all of them on disk with the successor lease.  The
        model may propose this action, never invoke it on its own liveness
        judgment.
        """
        workspace = self._existing_workspace(run_key)
        return self.store.force_reclaim(
            self.project_id,
            workspace.workspace_id,
            self.owner_id,
            expected_lease_id=expected_lease_id,
            expected_generation=expected_generation,
            reason=reason,
            authorized_by=authorized_by,
            ttl_seconds=ttl_seconds,
        )

    def recover(self, run_key: str) -> dict[str, Any]:
        """Disk truth for a run's workspace: current lease + settlement facts."""
        workspace = self._existing_workspace(run_key)
        try:
            lease = self.store.current_lease(workspace.workspace_id)
        except KeyError:
            lease = None
        # fleet slice 5 (G2): 重启后从盘上 facts 直接读出归属/结算计数（机械汇总，
        # 不做语义判断；last_parent_session_id 为最近一次 run_started 携带的非空归属）
        facts = self.store.list_facts(workspace.workspace_id)
        starts = [f for f in facts if f.get("event") == "run_started"]
        settles = [f for f in facts if f.get("event") == "run_settled"]
        last_parent = next(
            (
                str(f.get("parent_session_id"))
                for f in reversed(starts)
                if str(f.get("parent_session_id") or "")
            ),
            None,
        )
        return {
            "workspace_id": workspace.workspace_id,
            "lease": None
            if lease is None
            else {
                "lease_id": lease.lease_id,
                "generation": lease.generation,
                "worker_id": lease.worker_id,
                "owner_id": lease.owner_id,
                "state": lease.state,
                "expires_at": lease.expires_at,
                "expired": (
                    lease.expires_at is not None and time.time() >= lease.expires_at
                ),
                "remaining_seconds": (
                    None
                    if lease.expires_at is None
                    else lease.expires_at - time.time()
                ),
            },
            "settlement": None
            if (record := self.store.get_settlement(workspace.workspace_id)) is None
            else {
                "lease_id": record.lease_id,
                "generation": record.generation,
                "result": record.result,
            },
            "facts_summary": {
                "run_started": len(starts),
                "run_settled": len(settles),
                "last_parent_session_id": last_parent,
            },
        }
