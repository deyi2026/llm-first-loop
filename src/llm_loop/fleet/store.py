"""Durable fleet registry: projects, workspaces, worker leases, exactly-once settlement.

Disk is the only authority.  Every operation re-reads ``state.json`` under a
cross-process ``fcntl`` lock, so a stale coordinator handle can never win
against a newer generation written by another process (stale-generation
fencing).  Facts append to per-workspace JSONL; settlement is exactly-once
per workspace.

Round-2 race/expiry contract (measured in test_fleet_reclaim_race_and_ttl):

- ``reclaim`` is one atomic critical section (supersede + mint successor):
  racing reclaims serialize into takeover chains, never phantom actives;
- ``expected_generation`` makes recovery CAS: one winner, losers get
  ``LeaseConflictError``;
- ``acquire_lease`` refuses a live active lease (``LeaseConflictError``)
  instead of silently stacking a generation on top of it;
- leases may declare ``ttl_seconds``; ``reclaim_if_expired`` is the only
  time-licensed takeover path, and refuses expiry-free/unexpired leases
  with ``LeaseActiveError`` (live takeover stays an explicit reclaim);
- ``renew_lease`` lets the current holder extend its own expiry (fenced).
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


class LeaseConflictError(RuntimeError):
    """An acquisition/recovery lost the race against another lease generation."""


class LeaseActiveError(RuntimeError):
    """A live lease is not mechanically reclaimable (unexpired or expiry-free).

    ``remaining_seconds`` is the precise live window at raise time; ``None``
    means the lease declares no expiry at all (no window exists to race).
    """

    def __init__(self, message: str, *, remaining_seconds: float | None = None):
        super().__init__(message)
        self.remaining_seconds = remaining_seconds


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
    expires_at: float | None = None  # None = expiry-free: takeover needs an explicit reclaim


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

    def get_or_create_project(self, project_id: str) -> ProjectRecord:
        """Find-or-create under one lock: concurrent first sight cannot lose."""
        with self._lock():
            state = self._load()
            raw = state["projects"].get(project_id)
            if raw is None:
                raw = {
                    "project_id": project_id,
                    "created_at": _now(),
                    "workspaces": [],
                }
                state["projects"][project_id] = raw
                self._save(state)
            return ProjectRecord(
                project_id=raw["project_id"],
                created_at=raw["created_at"],
                workspaces=tuple(raw["workspaces"]),
            )

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

    def _workspace_from_raw(self, raw: dict[str, Any]) -> ExecutionWorkspace:
        return ExecutionWorkspace(
            workspace_id=raw["workspace_id"],
            project_id=raw["project_id"],
            physical_root=raw["physical_root"],
            repo_head=raw["repo_head"],
            created_at=raw["created_at"],
        )

    def find_workspace(self, project_id: str, physical_root: str) -> ExecutionWorkspace | None:
        """Read-only lookup by physical root; never creates state."""
        state = self._load()
        root = str(Path(physical_root))
        for raw in state["workspaces"].values():
            if raw["project_id"] == project_id and raw["physical_root"] == root:
                return self._workspace_from_raw(raw)
        return None

    def get_or_create_workspace(
        self, project_id: str, physical_root: str, repo_head: str
    ) -> ExecutionWorkspace:
        """Find-or-create under one lock: concurrent first sight cannot fork identities."""
        with self._lock():
            state = self._load()
            if project_id not in state["projects"]:
                raise KeyError(f"unknown project: {project_id}")
            root = str(Path(physical_root))
            for raw in state["workspaces"].values():
                if raw["project_id"] == project_id and raw["physical_root"] == root:
                    return self._workspace_from_raw(raw)
            workspace_id = f"ws-{len(state['workspaces']) + 1}"
            record = ExecutionWorkspace(
                workspace_id=workspace_id,
                project_id=project_id,
                physical_root=root,
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
            expires_at=raw.get("expires_at"),
        )

    def acquire_lease(
        self,
        project_id: str,
        workspace_id: str,
        owner_id: str,
        worker_id: str | None = None,
        ttl_seconds: float | None = None,
    ) -> WorkerLease:
        with self._lock():
            state = self._load()
            self._require_workspace(state, project_id, workspace_id)
            current = self._current_lease_raw(state, workspace_id)
            if current is not None and current["state"] == "settled":
                raise SettlementError(f"workspace already settled: {workspace_id}")
            if current is not None and current["state"] == "active":
                # never silently step on a live lease; takeover is reclaim's job
                raise LeaseConflictError(
                    f"active lease exists for {workspace_id} "
                    f"(generation {current['generation']}); explicit reclaim required"
                )
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
                expires_at=(
                    _now() + ttl_seconds if ttl_seconds is not None else None
                ),
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
                "expires_at": lease.expires_at,
            }
            self._save(state)
            return lease

    def reclaim(
        self,
        project_id: str,
        workspace_id: str,
        owner_id: str,
        *,
        expected_generation: int | None = None,
        ttl_seconds: float | None = None,
    ) -> WorkerLease:
        """Atomically supersede the current generation and issue the next one.

        One critical section: mark the observed lease superseded and mint the
        successor, so racing reclaims serialize into clean takeover chains and
        can never leave a phantom second ``active`` lease.  ``expected_generation``
        turns this into CAS crash recovery: if the observed stale generation
        already moved, the loser gets ``LeaseConflictError`` instead of a
        doomed lease.
        """
        with self._lock():
            state = self._load()
            self._require_workspace(state, project_id, workspace_id)
            current = self._current_lease_raw(state, workspace_id)
            if current is None:
                raise KeyError(f"no lease to reclaim: {workspace_id}")
            if current["state"] == "settled":
                raise SettlementError(f"workspace already settled: {workspace_id}")
            if (
                expected_generation is not None
                and current["generation"] != expected_generation
            ):
                raise LeaseConflictError(
                    f"reclaim raced: {workspace_id} moved to generation "
                    f"{current['generation']} (expected {expected_generation})"
                )
            current["state"] = "superseded"
            now = _now()
            generation = current["generation"] + 1
            lease = WorkerLease(
                lease_id=f"lease-{workspace_id}-g{generation}",
                project_id=project_id,
                workspace_id=workspace_id,
                worker_id=f"worker-g{generation}",
                generation=generation,
                owner_id=owner_id,
                acquired_at=now,
                state="active",
                expires_at=now + ttl_seconds if ttl_seconds is not None else None,
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
                "expires_at": lease.expires_at,
            }
            self._save(state)
            return lease

    def renew_lease(self, lease: WorkerLease, *, extend_seconds: float) -> WorkerLease:
        """Rolling-TTL heartbeat: expiry resets to ``now + extend_seconds``.

        R0 semantics: never cumulative -- each heartbeat is measured from the
        moment it beats, so a crash can never leave a phantom blocking window
        of stacked TTLs.  An expiry-free lease stays expiry-free (a heartbeat
        must not change takeover authority).  The holder fence is
        ``_require_current`` (active + current generation + unexpired), so an
        expired lease cannot renew itself back to life.
        """
        if extend_seconds <= 0:
            raise ValueError(f"extend_seconds must be positive: {extend_seconds}")
        with self._lock():
            state = self._load()
            self._require_current(state, lease)
            raw = state["leases"][lease.lease_id]
            now = _now()
            if raw.get("expires_at") is not None:
                raw["expires_at"] = now + extend_seconds
            self._save(state)
            return self._lease_from_raw(raw)

    def reclaim_if_expired(
        self,
        project_id: str,
        workspace_id: str,
        owner_id: str,
        *,
        expected_generation: int | None = None,
        ttl_seconds: float | None = None,
    ) -> WorkerLease:
        """Time-licensed takeover with generation CAS: only a lease past its
        declared expiry may pass, and only while the observed generation still
        holds (concurrent takeovers serialize into exactly one winner).

        Expiry-free or unexpired leases raise ``LeaseActiveError`` -- taking
        over a live lease without a time fact stays an explicit operator
        decision (``force_reclaim``).
        """
        with self._lock():
            state = self._load()
            self._require_workspace(state, project_id, workspace_id)
            current = self._current_lease_raw(state, workspace_id)
            if current is None:
                raise KeyError(f"no lease to reclaim: {workspace_id}")
            if current["state"] == "settled":
                raise SettlementError(f"workspace already settled: {workspace_id}")
            expires_at = current.get("expires_at")
            now = _now()
            if expires_at is None:
                raise LeaseActiveError(
                    f"lease {current['lease_id']} declares no expiry; "
                    "mechanical expiry reclaim refused (explicit reclaim required)"
                )
            if now < expires_at:
                raise LeaseActiveError(
                    f"lease {current['lease_id']} not expired "
                    f"(remaining {expires_at - now:.3f}s)",
                    remaining_seconds=expires_at - now,
                )
            if expected_generation is not None and current["generation"] != expected_generation:
                raise LeaseConflictError(
                    f"reclaim raced: {workspace_id} moved to generation "
                    f"{current['generation']} (expected {expected_generation})"
                )
            current["state"] = "superseded"
            generation = current["generation"] + 1
            lease = WorkerLease(
                lease_id=f"lease-{workspace_id}-g{generation}",
                project_id=project_id,
                workspace_id=workspace_id,
                worker_id=f"worker-g{generation}",
                generation=generation,
                owner_id=owner_id,
                acquired_at=now,
                state="active",
                expires_at=now + ttl_seconds if ttl_seconds is not None else None,
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
                "expires_at": lease.expires_at,
                "takeover": {
                    "kind": "expiry_reclaim",
                    "superseded_lease_id": current["lease_id"],
                    "at": now,
                },
            }
            self._save(state)
            return lease

    def force_reclaim(
        self,
        project_id: str,
        workspace_id: str,
        owner_id: str,
        *,
        expected_lease_id: str,
        expected_generation: int,
        reason: str,
        authorized_by: str,
        ttl_seconds: float | None = None,
    ) -> WorkerLease:
        """R0 live takeover: the ONLY way to supersede an unexpired/expiry-free
        lease.  Double CAS (lease id + generation) against the exact observed
        holder; mandatory non-empty ``reason``/``authorized_by`` recorded
        on-disk in the successor lease's ``takeover`` block for audit.
        """
        if not str(reason).strip() or not str(authorized_by).strip():
            raise ValueError(
                "force_reclaim requires a non-empty reason and authorized_by "
                "(operator decision must be recorded on disk)"
            )
        with self._lock():
            state = self._load()
            self._require_workspace(state, project_id, workspace_id)
            current = self._current_lease_raw(state, workspace_id)
            if current is None:
                raise KeyError(f"no lease to reclaim: {workspace_id}")
            if current["state"] == "settled":
                raise SettlementError(f"workspace already settled: {workspace_id}")
            if current["lease_id"] != expected_lease_id:
                raise LeaseConflictError(
                    f"force_reclaim raced: {workspace_id} current lease is "
                    f"{current['lease_id']} (expected {expected_lease_id})"
                )
            if current["generation"] != expected_generation:
                raise LeaseConflictError(
                    f"force_reclaim raced: {workspace_id} moved to generation "
                    f"{current['generation']} (expected {expected_generation})"
                )
            current["state"] = "superseded"
            now = _now()
            generation = current["generation"] + 1
            lease = WorkerLease(
                lease_id=f"lease-{workspace_id}-g{generation}",
                project_id=project_id,
                workspace_id=workspace_id,
                worker_id=f"worker-g{generation}",
                generation=generation,
                owner_id=owner_id,
                acquired_at=now,
                state="active",
                expires_at=now + ttl_seconds if ttl_seconds is not None else None,
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
                "expires_at": lease.expires_at,
                "takeover": {
                    "kind": "operator_force_reclaim",
                    "reason": reason,
                    "authorized_by": authorized_by,
                    "superseded_lease_id": current["lease_id"],
                    "at": now,
                },
            }
            self._save(state)
            return lease

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
        """Holder fence: current generation + active + (R0) not expired.

        TTL is authority, not a hint: once the declared window has passed, the
        holder loses every write right (facts, renew, settle) even before any
        successor exists -- a rival's ``reclaim_if_expired`` then cannot race
        a zombie back to life.
        """
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
        expires_at = current.get("expires_at")
        if expires_at is not None and _now() >= expires_at:
            raise FencedError(
                f"expired lease fenced: {lease.lease_id} window closed "
                f"{_now() - expires_at:.3f}s ago (TTL is authority)"
            )

    def lease_is_current(self, lease: WorkerLease) -> bool:
        """R1 effect-fence probe: read-only "is this lease still the writable authority?".

        Mirrors ``_require_current`` exactly (current generation + active +
        unexpired) so effect commit boundaries and settlement can never
        disagree.  Returns False instead of raising so side-effect gates can
        fail closed without exception control flow.  Never mutates state.
        """
        with self._lock():
            state = self._load()
            try:
                self._require_current(state, lease)
            except FencedError:
                return False
            return True

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
            # R0/R1 settlement fence, layered with exactly-once:
            #   stale or expired holder  -> FencedError  (never writes)
            #   current holder re-settle -> SettlementError (exactly-once)
            # A settled lease state alone is NOT a fence: only a *different*
            # current lease or a passed TTL removes settlement authority.
            current = self._current_lease_raw(state, lease.workspace_id)
            if (
                current is None
                or current["lease_id"] != lease.lease_id
                or current["state"] not in ("active", "settled")
            ):
                raise FencedError(
                    f"stale worker rejected: lease {lease.lease_id} "
                    f"is not the current generation of {lease.workspace_id}"
                )
            expires_at = current.get("expires_at")
            if expires_at is not None and _now() >= expires_at:
                raise FencedError(
                    f"expired lease fenced: {lease.lease_id} window closed "
                    f"{_now() - expires_at:.3f}s ago (TTL is authority)"
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
