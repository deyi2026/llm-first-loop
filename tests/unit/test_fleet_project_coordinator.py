"""ProjectCoordinator runtime wiring: run-boundary lease lifecycle (20260919 step-4).

Mechanical contract (DESIGN-20260919-fleet-minimal-slice):
- begin at run boundary (acquire; crash recovery = reclaim-with-supersede);
- fenced facts during the run;
- exactly-once settle at a real terminal (result is not None);
- crash leaves the durable active lease for the next coordinator to reclaim;
- SubAgentRunner without a coordinator must not touch any fleet state.
"""

from __future__ import annotations

import json

import pytest

from llm_loop.core.run_context import current_session_id
from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore
from llm_loop.fleet.coordinator import ProjectCoordinator
from llm_loop.fleet.store import FencedError, FleetStore, SettlementError
from llm_loop.llm.client import LLMResponse
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.registry import ToolRegistry


def _coordinator(tmp_path, owner="parent-1") -> ProjectCoordinator:
    return ProjectCoordinator(
        fleet_dir=tmp_path / "fleet",
        project_id="proj-1",
        physical_root=str(tmp_path / "proj"),
        repo_head="abc123",
        owner_id=owner,
    )


def _runner(tmp_path, llm, coordinator=None) -> SubAgentRunner:
    events = EventStore(tmp_path / "events", enabled=True)
    store = SessionStore(tmp_path / "sessions", event_store=events)
    return SubAgentRunner(  # type: ignore[arg-type]
        llm=llm,
        registry=ToolRegistry(),
        session_store=store,
        project_coordinator=coordinator,
    )


class _OneShotLLM:
    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        return LLMResponse(content="done", tool_calls=[], provider="fake")


def _fleet_state(tmp_path) -> dict:
    path = tmp_path / "fleet" / "state.json"
    assert path.exists(), "fleet state must exist"
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------- standalone


def test_run_boundary_lifecycle_attach_begin_fact_finish(tmp_path) -> None:
    coord = _coordinator(tmp_path)
    lease = coord.begin_run("child-1", worker_id="w1")
    assert lease.generation == 1
    assert lease.state == "active"
    coord.run_fact(lease, {"event": "run_started", "depth": 0})

    record = coord.finish_run(lease, {"outcome": "completed", "depth": 0})
    assert record.result["outcome"] == "completed"

    view = coord.recover("child-1")
    assert view["settlement"]["result"]["outcome"] == "completed"
    assert view["lease"]["state"] == "settled"

    # exactly-once: a second settlement attempt is rejected
    with pytest.raises(SettlementError):
        coord.finish_run(lease, {"outcome": "completed"})


def test_begin_run_after_crash_reclaims_and_fences_old_generation(tmp_path) -> None:
    crashed = _coordinator(tmp_path, owner="parent-1")
    stale_lease = crashed.begin_run("child-1", worker_id="w1")
    # crash: no fact, no settle; a fresh coordinator process reads the same disk

    fresh = _coordinator(tmp_path, owner="parent-2")
    new_lease = fresh.begin_run("child-1", worker_id="w2")
    assert new_lease.generation == 2

    view = fresh.recover("child-1")
    assert view["lease"]["lease_id"] == new_lease.lease_id
    raw = json.loads((tmp_path / "fleet" / "state.json").read_text(encoding="utf-8"))
    assert raw["leases"][stale_lease.lease_id]["state"] == "superseded"

    # the zombie worker's late writes and settlement are fenced, not merged
    with pytest.raises(FencedError):
        crashed.run_fact(stale_lease, {"event": "late_fact"})
    with pytest.raises(FencedError):
        crashed.finish_run(stale_lease, {"outcome": "completed"})


def test_begin_run_rejects_settled_workspace(tmp_path) -> None:
    coord = _coordinator(tmp_path)
    lease = coord.begin_run("child-1", worker_id="w1")
    coord.finish_run(lease, {"outcome": "completed"})
    with pytest.raises(SettlementError):
        coord.begin_run("child-1", worker_id="w2")


# ----------------------------------------------------- SubAgentRunner wiring


def test_child_run_settles_fleet_workspace(tmp_path) -> None:
    coord = _coordinator(tmp_path)
    runner = _runner(tmp_path, _OneShotLLM(), coordinator=coord)
    tok = current_session_id.set("parent-run-1")
    try:
        result = runner.run("trivial child", depth=0)
    finally:
        current_session_id.reset(tok)

    assert result.outcome == "completed"
    state = _fleet_state(tmp_path)
    assert len(state["workspaces"]) == 1
    assert len(state["settlements"]) == 1
    settlement = next(iter(state["settlements"].values()))
    assert settlement["result"]["outcome"] == "completed"
    facts = FleetStore(tmp_path / "fleet").list_facts(settlement["workspace_id"])
    assert any(f.get("event") == "run_started" for f in facts)


def test_child_crash_leaves_active_lease_then_reclaim_fences(tmp_path, monkeypatch) -> None:
    coord = _coordinator(tmp_path)
    runner = _runner(tmp_path, _OneShotLLM(), coordinator=coord)

    def _boom(**kwargs):  # noqa: ANN003
        raise RuntimeError("simulated crash before any terminal")

    monkeypatch.setattr(runner, "_run_reserved_child", _boom)
    tok = current_session_id.set("parent-run-1")
    try:
        with pytest.raises(RuntimeError, match="simulated crash"):
            runner.run("crashing child", depth=0)
    finally:
        current_session_id.reset(tok)

    # crash state is durable: active lease, no settlement
    state = _fleet_state(tmp_path)
    assert len(state["settlements"]) == 0
    leases = [raw for raw in state["leases"].values() if raw["state"] == "active"]
    assert len(leases) == 1

    workspace_id = leases[0]["workspace_id"]
    fresh = _coordinator(tmp_path, owner="parent-2")
    new_lease = fresh.reclaim_run(workspace_id)
    assert new_lease.generation == 2


def test_runner_without_coordinator_has_no_fleet_state(tmp_path) -> None:
    runner = _runner(tmp_path, _OneShotLLM(), coordinator=None)
    tok = current_session_id.set("parent-run-2")
    try:
        result = runner.run("trivial child", depth=0)
    finally:
        current_session_id.reset(tok)
    assert result.outcome == "completed"
    assert not (tmp_path / "fleet").exists()
