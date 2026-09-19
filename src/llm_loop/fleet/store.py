"""Durable fleet registry: projects, workspaces, worker leases, exactly-once settlement.

Disk is the only authority.  Every operation re-reads ``state.json`` under a
cross-process ``fcntl`` lock, so a stale coordinator handle can never win
against a newer generation written by another process (stale-generation
fencing).  Facts append to per-workspace JSONL; settlement is exactly-once
per workspace.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA = "lfl.fleet.registry/v1"


class FencedError(RuntimeError):
    """A write/result arrived from a worker that is not the current generation."""


class SettlementError(RuntimeError):
    """A workspace already settled exactly once; no further settlement exists."""


@dataclass(frozen=True)
class ProjectRecord:
    project_id: str
    created_at: float
    workspaces: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExecutionWorkspace:
    workspace_id: str
    project_id: str
    physical_root: str
    repo_head: str
    created_at: float


@dataclass(frozen=True)
class WorkerLease:
    lease_id: str
    project_id: str
    workspace_id: str
    worker_id: str
    generation: int
    owner_id: str
    acquired_at: float
    state: str  # active | superseded | settled


@dataclass(frozen=True)
class SettlementRecord:
    lease_id: str
    project_id: str
    workspace_id: str
    worker_id: str
    generation: int
    result: dict[str, Any]
    settled_at: float


def _now() -> float:
    return time.time()


class FleetStore:
    """Closed-schema durable registry; disk truth only, no in-memory authority."""

    def __init__(self, fleet_dir: str | Path) -> None:
        self.dir = Path(fleet_dir).expanduser().resolve()
        self.state_path = self.dir / "state.json"
        self.lock_path = self.dir / "fleet.lock"
        self.facts_dir = self.dir / "facts"

    # ------------------------------------------------------------------ io

    @contextmanager
    def _lock(self) -> Iterator[None]:
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "schema": SCHEMA,
                "projects": {},
                "workspaces": {},
                "leases": {},
                "settlements": {},
            }
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        if raw.get("schema") != SCHEMA:
            raise RuntimeError(f"unknown fleet state schema: {raw.get('schema')!r}")
        return raw

    def _save(self, state: dict[str, Any]) -> None:
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_path)

    # ------------------------------------------------------- construction

    def create_project(self, project_id: str) -> ProjectRecord:
        with self._lock():
            state = self._load()
            if project_id in state["projects"]:
                raise KeyError(f"project already exists: {project_id}")
            record = ProjectRecord(project_id=project_id, created_at=_now())
            state["projects"][project_id] = {
                "project_id": record.project_id,
                "created_at": record.created_at,
                "workspaces": [],
            }
            self._save(state)
            return record

    def create_workspace(
        self, project_id: str, physical_root: str, repo_head: str
    ) -> ExecutionWorkspace:
        with self._lock():
            state = self._load()
            if project_id not in state["projects"]:
                raise KeyError(f"unknown project: {project_id}")
            workspace_id = f"ws-{len(state['workspaces']) + 1}"
            record = ExecutionWorkspace(
                workspace_id=workspace_id,
                project_id=project_id,
                physical_root=str(Path(physical_root)),
                repo_head=repo_head,
                created_at=_now(),
            )
            state["workspaces"][workspace_id] = {
                "workspace_id": record.workspace_id,
                "project_id": record.project_id,
                "physical_root": record.physical_root,
                "repo_head": record.repo_head,
                "created_at": record.created_at,
            }
            state["projects"][project_id]["workspaces"].append(workspace_id)
            self._save(state)
            return record

    def _lease_from_raw(self, raw: dict[str, Any]) -> WorkerLease:
        return WorkerLease(
            lease_id=raw["lease_id"],
            project_id=raw["project_id"],
            workspace_id=raw["workspace_id"],
            worker_id=raw["worker_id"],
            generation=raw["generation"],
            owner_id=raw["owner_id"],
            acquired_at=raw["acquired_at"],
            state=raw["state"],
        )

    def acquire_lease(
        self,
        project_id: str,
        workspace_id: str,
        owner_id: str,
        worker_id: str | None = None,
    ) -> WorkerLease:
        with self._lock():
            state = self._load()
            self._require_workspace(state, project_id, workspace_id)
            current = self._current_lease_raw(state, workspace_id)
            if current is not None and current["state"] == "settled":
                raise SettlementError(f"workspace already settled: {workspace_id}")
            generation = (current["generation"] + 1) if current else 1
            lease = WorkerLease(
                lease_id=f"lease-{workspace_id}-g{generation}",
                project_id=project_id,
                workspace_id=workspace_id,
                worker_id=worker_id or f"worker-g{generation}",
                generation=generation,
                owner_id=owner_id,
                acquired_at=_now(),
                state="active",
            )
            state["leases"][lease.lease_id] = {
                "lease_id": lease.lease_id,
                "project_id": lease.project_id,
                "workspace_id": lease.workspace_id,
                "worker_id": lease.worker_id,
                "generation": lease.generation,
                "owner_id": lease.owner_id,
                "acquired_at": lease.acquired_at,
                "state": lease.state,
            }
            self._save(state)
            return lease

    def reclaim(self, project_id: str, workspace_id: str, owner_id: str) -> WorkerLease:
        """Mark the current generation superseded and issue the next one (CAS)."""
        with self._lock():
            state = self._load()
            self._require_workspace(state, project_id, workspace_id)
            current = self._current_lease_raw(state, workspace_id)
            if current is None:
                raise KeyError(f"no lease to reclaim: {workspace_id}")
            if current["state"] == "settled":
                raise SettlementError(f"workspace already settled: {workspace_id}")
            current["state"] = "superseded"
            self._save(state)
        return self.acquire_lease(project_id, workspace_id, owner_id)

    # ------------------------------------------------------------- guards

    def _require_workspace(
        self, state: dict[str, Any], project_id: str, workspace_id: str
    ) -> None:
        raw = state["workspaces"].get(workspace_id)
        if raw is None or raw["project_id"] != project_id:
            raise KeyError(f"unknown workspace for project: {project_id}/{workspace_id}")

    def _current_lease_raw(
        self, state: dict[str, Any], workspace_id: str
    ) -> dict[str, Any] | None:
        candidates = [
            raw
            for raw in state["leases"].values()
            if raw["workspace_id"] == workspace_id
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda raw: raw["generation"])

    def _require_current(self, state: dict[str, Any], lease: WorkerLease) -> None:
        current = self._current_lease_raw(state, lease.workspace_id)
        if (
            current is None
            or current["lease_id"] != lease.lease_id
            or current["state"] != "active"
        ):
            raise FencedError(
                f"stale worker rejected: lease {lease.lease_id} "
                f"is not the current active generation of {lease.workspace_id}"
            )

    # ------------------------------------------------------------ facts

    def record_fact(self, lease: WorkerLease, fact: dict[str, Any]) -> None:
        with self._lock():
            state = self._load()
            self._require_current(state, lease)
            self.facts_dir.mkdir(parents=True, exist_ok=True)
            path = self.facts_dir / f"{lease.workspace_id}.jsonl"
            entry = {
                "lease_id": lease.lease_id,
                "generation": lease.generation,
                "recorded_at": _now(),
                "fact": fact,
            }
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ------------------------------------------------------- settlement

    def settle(self, lease: WorkerLease, result: dict[str, Any]) -> SettlementRecord:
        with self._lock():
            state = self._load()
            current = self._current_lease_raw(state, lease.workspace_id)
            if current is None or current["lease_id"] != lease.lease_id:
                raise FencedError(
                    f"stale worker rejected: lease {lease.lease_id} "
                    f"is not the current generation of {lease.workspace_id}"
                )
            if lease.workspace_id in state["settlements"]:
                raise SettlementError(
                    f"exactly-once violated: {lease.workspace_id} already settled"
                )
            record = SettlementRecord(
                lease_id=lease.lease_id,
                project_id=lease.project_id,
                workspace_id=lease.workspace_id,
                worker_id=lease.worker_id,
                generation=lease.generation,
                result=result,
                settled_at=_now(),
            )
            state["settlements"][lease.workspace_id] = {
                "lease_id": record.lease_id,
                "project_id": record.project_id,
                "workspace_id": record.workspace_id,
                "worker_id": record.worker_id,
                "generation": record.generation,
                "result": record.result,
                "settled_at": record.settled_at,
            }
            state["leases"][lease.lease_id]["state"] = "settled"
            self._save(state)
            return record

    # ------------------------------------------------------------- reads

    def get_project(self, project_id: str) -> ProjectRecord:
        raw = self._load()["projects"].get(project_id)
        if raw is None:
            raise KeyError(f"unknown project: {project_id}")
        return ProjectRecord(
            project_id=raw["project_id"],
            created_at=raw["created_at"],
            workspaces=tuple(raw.get("workspaces", ())),
        )

    def get_workspace(self, workspace_id: str) -> ExecutionWorkspace:
        raw = self._load()["workspaces"].get(workspace_id)
        if raw is None:
            raise KeyError(f"unknown workspace: {workspace_id}")
        return ExecutionWorkspace(
            workspace_id=raw["workspace_id"],
            project_id=raw["project_id"],
            physical_root=raw["physical_root"],
            repo_head=raw["repo_head"],
            created_at=raw["created_at"],
        )

    def current_lease(self, workspace_id: str) -> WorkerLease:
        state = self._load()
        raw = self._current_lease_raw(state, workspace_id)
        if raw is None:
            raise KeyError(f"no lease for workspace: {workspace_id}")
        return self._lease_from_raw(raw)

    def get_settlement(self, workspace_id: str) -> SettlementRecord | None:
        raw = self._load()["settlements"].get(workspace_id)
        if raw is None:
            return None
        return SettlementRecord(
            lease_id=raw["lease_id"],
            project_id=raw["project_id"],
            workspace_id=raw["workspace_id"],
            worker_id=raw["worker_id"],
            generation=raw["generation"],
            result=raw["result"],
            settled_at=raw["settled_at"],
        )

    def list_facts(self, workspace_id: str) -> list[dict[str, Any]]:
        path = self.facts_dir / f"{workspace_id}.jsonl"
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line)["fact"])
        return entries
