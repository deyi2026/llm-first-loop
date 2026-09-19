"""Fleet minimal vertical slice: crash → restart → reclaim → stale fencing → exactly-once settlement.

The program answers exactly one authority question:
"Does this physical worker currently hold the right to commit side
effects/results for this generation of this workspace?"
Everything semantic stays with the model/coordinator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_loop.fleet.store import (
    FencedError,
    FleetStore,
    SettlementError,
    WorkerLease,
)


def _store(root: Path) -> FleetStore:
    return FleetStore(root / "fleet")


def test_gate_crash_reclaim_exactly_once(tmp_path: Path) -> None:
    """The full 10-step crash/reclaim Gate as one deterministic chain."""
    # 1. Project P creates Workspace W.
    s1 = _store(tmp_path)
    project = s1.create_project("proj-1")
    assert project.project_id == "proj-1"
    workspace = s1.create_workspace(
        project_id="proj-1",
        physical_root=str(tmp_path / "ws-root"),
        repo_head="2939deea6f093b2851de61c24c01fa1a169b835b",
    )
    assert workspace.project_id == "proj-1"
    assert Path(workspace.physical_root) == tmp_path / "ws-root"

    # 2. Worker generation G1 acquires the lease.
    g1 = s1.acquire_lease(
        project_id="proj-1", workspace_id=workspace.workspace_id,
        worker_id="worker-a", owner_id="owner-A",
    )
    assert g1.generation == 1

    # 3. G1 works and produces partial durable facts.
    s1.record_fact(g1, {"step": "collect", "evidence": "evidence://v1/a"})
    s1.record_fact(g1, {"step": "analyze", "progress": "half"})

    # 4. Owner process truly disappears (no release; nothing in memory).

    # 5. A new coordinator recovers Project/Workspace/Worker facts from disk.
    s2 = _store(tmp_path)  # fresh instance = new coordinator, disk is the only bridge
    recovered_project = s2.get_project("proj-1")
    assert recovered_project.project_id == project.project_id
    assert recovered_project.created_at == project.created_at
    assert recovered_project.workspaces == (workspace.workspace_id,)
    recovered_workspace = s2.get_workspace(workspace.workspace_id)
    assert recovered_workspace == workspace
    assert s2.current_lease(workspace.workspace_id) == g1

    # 6. New owner reclaims -> generation G2.
    g2 = s2.reclaim("proj-1", workspace.workspace_id, owner_id="owner-B")
    assert g2.generation == 2
    assert g2.worker_id != g1.worker_id or g2.owner_id != g1.owner_id

    # 7. G1's late writes and late results must fail closed.
    with pytest.raises(FencedError):
        s1.record_fact(g1, {"step": "late-write"})
    with pytest.raises(FencedError):
        s1.settle(g1, {"result": "stale-from-g1"})

    # 8. G2 continues execution.
    s2.record_fact(g2, {"step": "finish", "progress": "done"})

    # 9. Exactly one result can settle to the parent project.
    settlement = s2.settle(g2, {"result": "final-from-g2"})
    assert settlement.project_id == "proj-1"
    with pytest.raises(SettlementError):
        s2.settle(g2, {"result": "duplicate"})
    with pytest.raises(FencedError):
        s1.settle(g1, {"result": "late-g1"})

    # 10. Restart again proves the same terminal state.
    s3 = _store(tmp_path)
    final = s3.get_settlement(workspace.workspace_id)
    assert final is not None
    assert final.lease_id == settlement.lease_id
    assert final.result == {"result": "final-from-g2"}
    facts = s3.list_facts(workspace.workspace_id)
    assert [f["step"] for f in facts] == ["collect", "analyze", "finish"]
    with pytest.raises(FencedError):
        s3.record_fact(g1, {"step": "post-mortem-write"})


def test_lease_identity_is_mechanical_and_closed(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.create_project("p")
    w = s.create_workspace("p", physical_root=str(tmp_path / "w"), repo_head="deadbeef")
    lease = s.acquire_lease("p", w.workspace_id, worker_id="wk", owner_id="ow")
    # The lease is the five mechanical coordinates; nothing more.
    assert (lease.project_id, lease.workspace_id, lease.worker_id,
            lease.generation, lease.owner_id) == ("p", w.workspace_id, "wk", 1, "ow")


def test_unknown_parent_ids_fail_closed(tmp_path: Path) -> None:
    s = _store(tmp_path)
    with pytest.raises(KeyError):
        s.create_workspace("no-such-project", physical_root="/tmp/x", repo_head="x")
    s.create_project("p")
    w = s.create_workspace("p", physical_root="/tmp/w", repo_head="x")
    with pytest.raises(KeyError):
        s.acquire_lease("p", "no-such-workspace", worker_id="wk", owner_id="ow")
    with pytest.raises(KeyError):
        s.acquire_lease("no-such-project", w.workspace_id, worker_id="wk", owner_id="ow")


def test_forged_lease_coordinates_are_fenced(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.create_project("p")
    w = s.create_workspace("p", physical_root="/tmp/w", repo_head="x")
    g1 = s.acquire_lease("p", w.workspace_id, worker_id="wk", owner_id="ow")
    g2 = s.reclaim("p", w.workspace_id, owner_id="ow2")
    # A forged handle re-using stale coordinates must fail closed.
    stale = WorkerLease(
        project_id="p", workspace_id=w.workspace_id, worker_id="wk",
        generation=g1.generation, owner_id="ow", lease_id=g1.lease_id,
        acquired_at=g1.acquired_at, state="active",
    )
    assert stale == g1
    with pytest.raises(FencedError):
        s.record_fact(stale, {"step": "forged"})
    assert g2.generation > g1.generation


def test_persistence_is_json_and_atomic_layout(tmp_path: Path) -> None:
    s = _store(tmp_path)
    s.create_project("p")
    w = s.create_workspace("p", physical_root="/tmp/w", repo_head="x")
    lease = s.acquire_lease("p", w.workspace_id, worker_id="wk", owner_id="ow")
    raw = json.loads((tmp_path / "fleet" / "state.json").read_text(encoding="utf-8"))
    assert raw["schema"] == "lfl.fleet.registry/v1"
    assert raw["projects"]["p"]["project_id"] == "p"
    assert raw["leases"][lease.lease_id]["generation"] == 1
