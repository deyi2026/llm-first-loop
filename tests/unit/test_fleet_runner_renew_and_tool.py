"""Third fleet slice: TTL + renew inside the real SubAgentRunner lifecycle,
plus the coordinator's recover() facts (expires_at / expired) exposed on the
model tool surface.

Mechanical contract (checkpoint 2026-09-19 slice 3):
- SubAgentRunner attaches a bounded lease (ttl wired through the runner);
- every round boundary renews the lease (heartbeat while genuinely alive);
- renew failure is fail-soft: the authority boundary stays the fence at settle;
- a crashed lease past its ttl reads expired=true through the tool surface;
- the tool fails closed when the runner has no coordinator / unknown workspace.
"""

from __future__ import annotations

import json
import time

import pytest

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore
from llm_loop.fleet.coordinator import ProjectCoordinator
from llm_loop.llm.client import LLMResponse
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.builtin.subagent_lease import SubAgentLeaseTool
from llm_loop.tools.registry import ToolRegistry


def _coordinator(tmp_path, owner="parent-1") -> ProjectCoordinator:
    return ProjectCoordinator(
        fleet_dir=tmp_path / "fleet",
        project_id="proj-1",
        physical_root=str(tmp_path / "proj"),
        repo_head="abc123",
        owner_id=owner,
    )


def _runner(tmp_path, llm, coordinator=None, ttl=900.0) -> SubAgentRunner:
    events = EventStore(tmp_path / "events", enabled=True)
    store = SessionStore(tmp_path / "sessions", event_store=events)
    return SubAgentRunner(  # type: ignore[arg-type]
        llm=llm,
        registry=ToolRegistry(),
        session_store=store,
        project_coordinator=coordinator,
        fleet_lease_ttl_seconds=ttl,
    )


class _SeqLLM:
    def __init__(self, responses) -> None:
        self._responses = list(responses)

    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        if not self._responses:
            return LLMResponse(content="done", tool_calls=[], provider="fake")
        return self._responses.pop(0)


class _OneShotLLM:
    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        return LLMResponse(content="done", tool_calls=[], provider="fake")


def _two_round_llm() -> _SeqLLM:
    return _SeqLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[
                    ToolCall(id="c1", name="no_such_tool", arguments={"x": 1})
                ],
                provider="fake",
            ),
            LLMResponse(content="done", tool_calls=[], provider="fake"),
        ]
    )


def _fleet_state(tmp_path) -> dict:
    path = tmp_path / "fleet" / "state.json"
    assert path.exists(), "fleet state must exist"
    return json.loads(path.read_text(encoding="utf-8"))


def _run_key_of(tmp_path) -> str:
    """The workspace run_key (= child session id) from durable state."""
    state = _fleet_state(tmp_path)
    row = next(iter(state["workspaces"].values()))
    root = str(row["physical_root"]).rstrip("/")
    return root.rsplit("/", 1)[-1]


def _run_parent(runner, task: str):
    tok = current_session_id.set("parent-run-1")
    try:
        return runner.run(task, depth=0)
    finally:
        current_session_id.reset(tok)


# ------------------------------------------------------------------ renew/TTL


def test_runner_attaches_bounded_lease_and_renews_each_round(tmp_path, monkeypatch) -> None:
    coord = _coordinator(tmp_path)
    runner = _runner(tmp_path, _two_round_llm(), coordinator=coord, ttl=300.0)
    renew_seen: list[float] = []
    real = runner._renew_fleet_run

    def spy(sid: str) -> None:
        real(sid)
        lease = runner._fleet_leases.get(sid)
        if lease is not None:
            renew_seen.append(float(lease.expires_at or 0.0))

    monkeypatch.setattr(runner, "_renew_fleet_run", spy)
    result = _run_parent(runner, "multi-round child")
    assert result.outcome == "completed"

    assert len(renew_seen) >= 2, "each round boundary must renew the lease"
    assert all(b > a for a, b in zip(renew_seen, renew_seen[1:], strict=False)), (
        "renew must strictly extend expires_at while the child is alive"
    )

    run_key = _run_key_of(tmp_path)
    view = coord.recover(run_key)
    assert view["lease"]["expires_at"] is not None
    assert view["lease"]["state"] == "settled"


def test_renew_failure_is_failsoft_and_fence_stays_at_settle(tmp_path, monkeypatch) -> None:
    coord = _coordinator(tmp_path)
    runner = _runner(tmp_path, _two_round_llm(), coordinator=coord, ttl=300.0)
    rival = _coordinator(tmp_path, owner="rival-1")
    real = runner._renew_fleet_run
    reclaimed: dict[str, str] = {}

    def rival_then_renew(sid: str) -> None:
        lease = runner._fleet_leases.get(sid)
        if lease is not None and not reclaimed:
            reclaimed["workspace"] = lease.workspace_id
            # supersede mid-run: the original generation gets fenced on disk
            rival.reclaim_run(lease.workspace_id)
        real(sid)  # must raise fail-soft internally, never kill the child loop

    monkeypatch.setattr(runner, "_renew_fleet_run", rival_then_renew)
    result = _run_parent(runner, "contested child")
    assert result.outcome == "completed", "renew failure must not kill the child run"

    assert len(_fleet_state(tmp_path)["settlements"]) == 0, "fenced settle must be fail-soft, not merged"
    lease_rows = list(_fleet_state(tmp_path)["leases"].values())
    assert any(row["state"] == "superseded" for row in lease_rows)
    assert any(
        row["state"] == "active" and row["generation"] == 2 for row in lease_rows
    ), "rival holds the reclaimed lease"


# ------------------------------------------------------------- tool surface


def test_crashed_expired_lease_visible_on_tool_surface(tmp_path, monkeypatch) -> None:
    coord = _coordinator(tmp_path)
    runner = _runner(tmp_path, _OneShotLLM(), coordinator=coord, ttl=0.15)

    def _boom(**kwargs):  # noqa: ANN003
        raise RuntimeError("simulated crash before any terminal")

    monkeypatch.setattr(runner, "_run_reserved_child", _boom)
    with pytest.raises(RuntimeError, match="simulated crash"):
        _run_parent(runner, "crash child")

    time.sleep(0.25)  # let the bounded lease really expire

    run_key = _run_key_of(tmp_path)

    tool = SubAgentLeaseTool(runner)
    res = tool.execute(child_id=run_key)
    assert res.status == ToolResultStatus.SUCCESS
    assert "workspace_id=" in res.content
    assert "expires_at=" in res.content
    assert "expired=true" in res.content
    assert "state=active" in res.content


def test_subagent_lease_tool_reports_settled_child(tmp_path) -> None:
    coord = _coordinator(tmp_path)
    runner = _runner(tmp_path, _OneShotLLM(), coordinator=coord, ttl=60.0)
    result = _run_parent(runner, "trivial child")
    assert result.outcome == "completed"

    run_key = _run_key_of(tmp_path)
    tool = SubAgentLeaseTool(runner)
    res = tool.execute(child_id=run_key)
    assert res.status == ToolResultStatus.SUCCESS
    assert "state=settled" in res.content
    assert "settlement=settled" in res.content or "outcome=" in res.content


def test_subagent_lease_tool_fails_closed(tmp_path) -> None:
    # no coordinator -> surface not enabled
    runner_plain = _runner(tmp_path, _OneShotLLM(), coordinator=None)
    tool = SubAgentLeaseTool(runner_plain)
    res = tool.execute(child_id="anything")
    assert res.status == ToolResultStatus.FAILURE
    assert "未接入" in res.content or "not enabled" in res.content

    # coordinator present but workspace unknown on disk -> honest miss
    runner = _runner(tmp_path, _OneShotLLM(), coordinator=_coordinator(tmp_path))
    res2 = SubAgentLeaseTool(runner).execute(child_id="ghost-id")
    assert res2.status == ToolResultStatus.FAILURE
    assert "不存在" in res2.content or "not found" in res2.content


def test_recover_is_readonly_no_silent_workspace_creation(tmp_path) -> None:
    coord = _coordinator(tmp_path)
    with pytest.raises(KeyError):
        coord.recover("never-begun-run")
    state = _fleet_state(tmp_path)
    assert len(state["workspaces"]) == 0, "recover must never create workspace state"
