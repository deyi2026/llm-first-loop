"""ProjectCoordinator: bind the FleetStore lease lifecycle to run boundaries.

This is the runtime adapter from DESIGN-20260919-fleet-minimal-slice step 4:

- ``begin_run``  - at a run boundary.  Creates the per-run workspace on first
  sight (deterministic ``<physical_root>/runs/<run_key>`` identity), then
  acquires the lease.  If the previous generation crashed without a terminal
  (durable active lease), the old generation is explicitly superseded via
  ``reclaim`` -- crash recovery at the boundary, recorded on disk.
- ``run_fact``   - fenced append during the run.
- ``finish_run`` - exactly-once settlement at a real terminal.
- ``reclaim_run``/``recover`` - recovery surface for the next coordinator.

The program keeps mechanical facts only (identity, generation, fencing,
exactly-once).  When to reclaim a *live* lease stays a model/operator
decision; a crashed lease is reclaimed mechanically at the next begin.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from llm_loop.fleet.store import (
    ExecutionWorkspace,
    FleetStore,
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
            # crashed predecessor without a terminal: supersede it explicitly,
            # CAS on the generation we observed so concurrent recoveries have
            # exactly one winner and the losers get LeaseConflictError
            return self.store.reclaim(
                self.project_id,
                workspace.workspace_id,
                self.owner_id,
                expected_generation=current.generation,
                ttl_seconds=ttl_seconds,
            )
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
        workspace = self._workspace_for(run_key)
        return self.store.reclaim_if_expired(
            self.project_id, workspace.workspace_id, self.owner_id,
            ttl_seconds=ttl_seconds,
        )

    def recover(self, run_key: str) -> dict[str, Any]:
        """Disk truth for a run's workspace: current lease + settlement facts."""
        workspace = self._workspace_for(run_key)
        try:
            lease = self.store.current_lease(workspace.workspace_id)
        except KeyError:
            lease = None
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
            },
            "settlement": None
            if (record := self.store.get_settlement(workspace.workspace_id)) is None
            else {
                "lease_id": record.lease_id,
                "generation": record.generation,
                "result": record.result,
            },
        }
