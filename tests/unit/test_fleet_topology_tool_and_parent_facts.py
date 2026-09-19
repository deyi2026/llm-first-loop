"""Fleet slice 5: spawn fact 归属绑定（G2）+ 拓扑/租约合并只读工具面（G3）。

Contract（用户确认 2026-09-19）:
- G2: run_started/run_settled facts 携带 parent_session_id；重启后（新
  coordinator 实例）recover() 直接从盘上 facts 读出归属。
- G3: 只读工具 subagent_topology：按 child 或 parent 返回拓扑 + 租约合并
  disk-truth 视图；coordinator 未接入时租约块如实 unavailable（拓扑仍可用）；
  无参数 fail-closed；不产生任何写。
"""

from __future__ import annotations

import json

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import current_session_id
from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore
from llm_loop.fleet.coordinator import ProjectCoordinator
from llm_loop.llm.client import LLMResponse
from llm_loop.subagent.runner import SubAgentRunner
from llm_loop.tools.builtin.subagent_topology import SubagentTopologyTool
from llm_loop.tools.registry import ToolRegistry


def _coordinator(tmp_path, owner="parent-1") -> ProjectCoordinator:
    return ProjectCoordinator(
        fleet_dir=tmp_path / "fleet",
        project_id="proj-1",
        physical_root=str(tmp_path / "proj"),
        repo_head="abc123",
        owner_id=owner,
    )


def _runner(tmp_path, coordinator=None, llm=None) -> SubAgentRunner:
    events = EventStore(tmp_path / "events", enabled=True)
    store = SessionStore(tmp_path / "sessions", event_store=events)
    return SubAgentRunner(  # type: ignore[arg-type]
        llm=llm or _OneShotLLM(),
        registry=ToolRegistry(),
        session_store=store,
        project_coordinator=coordinator,
    )


class _OneShotLLM:
    def chat(self, messages, tools, **kwargs):  # noqa: ANN001, ANN201, ARG002
        return LLMResponse(content="done", tool_calls=[], provider="fake")


def _run_parent(runner, task: str = "single-round child"):
    tok = current_session_id.set("parent-run-1")
    try:
        return runner.run(task, depth=0)
    finally:
        current_session_id.reset(tok)


def _run_key_of(tmp_path) -> str:
    state = json.loads((tmp_path / "fleet" / "state.json").read_text(encoding="utf-8"))
    row = next(iter(state["workspaces"].values()))
    root = str(row["physical_root"]).rstrip("/")
    return root.rsplit("/", 1)[-1]


# ---------------------------------------------------------------- G2


def test_spawn_facts_carry_parent_binding(tmp_path) -> None:
    coord = _coordinator(tmp_path)
    runner = _runner(tmp_path, coordinator=coord)
    result = _run_parent(runner)
    assert result.outcome == "completed"

    run_key = _run_key_of(tmp_path)
    facts = coord.store.list_facts(coord.recover(run_key)["workspace_id"])
    started = [f for f in facts if f.get("event") == "run_started"]
    settled = [f for f in facts if f.get("event") == "run_settled"]
    assert started, "run_started fact must exist"
    assert started[0].get("parent_session_id") == "parent-run-1"
    assert settled and settled[-1].get("parent_session_id") == "parent-run-1"


def test_recover_surfaces_parent_binding_after_restart(tmp_path) -> None:
    coord = _coordinator(tmp_path)
    runner = _runner(tmp_path, coordinator=coord)
    assert _run_parent(runner).outcome == "completed"

    run_key = _run_key_of(tmp_path)
    restarted = _coordinator(tmp_path, owner="restarter-1")
    view = restarted.recover(run_key)
    summary = view["facts_summary"]
    assert summary["run_started"] >= 1
    assert summary["run_settled"] >= 1
    assert summary["last_parent_session_id"] == "parent-run-1"


# ---------------------------------------------------------------- G3


def test_topology_tool_child_view_merges_topology_and_lease(tmp_path) -> None:
    coord = _coordinator(tmp_path)
    runner = _runner(tmp_path, coordinator=coord)
    assert _run_parent(runner).outcome == "completed"
    run_key = _run_key_of(tmp_path)

    tool = SubagentTopologyTool(runner)
    result = tool.execute(child_id=run_key)
    assert result.status is ToolResultStatus.SUCCESS
    text = result.content
    assert "parent_session_id=parent-run-1" in text
    assert "state=settled" in text


def test_topology_tool_parent_view_lists_children_and_leases(tmp_path) -> None:
    coord = _coordinator(tmp_path)
    runner = _runner(tmp_path, coordinator=coord)
    assert _run_parent(runner).outcome == "completed"

    tool = SubagentTopologyTool(runner)
    result = tool.execute(parent_id="parent-run-1")
    assert result.status is ToolResultStatus.SUCCESS
    assert "parent_id=parent-run-1" in result.content


def test_topology_tool_lease_unavailable_without_coordinator(tmp_path) -> None:
    runner = _runner(tmp_path, coordinator=None)
    tool = SubagentTopologyTool(runner)
    result = tool.execute(child_id="no-such-child")
    # 拓扑路径仍可用（journal 是 session-store 面），租约块如实 unavailable
    assert result.status is ToolResultStatus.SUCCESS
    assert "lease: unavailable" in result.content


def test_topology_tool_requires_an_argument(tmp_path) -> None:
    runner = _runner(tmp_path, coordinator=None)
    tool = SubagentTopologyTool(runner)
    result = tool.execute()
    assert result.status is ToolResultStatus.FAILURE


def test_factory_registers_topology_tool_with_fleet_off(tmp_path) -> None:
    """factory 注册面：fleet 未开启也注册该工具（租约块届时如实 unavailable）。"""
    from llm_loop.config import Settings
    from llm_loop.factory import build_engine

    engine = build_engine(
        Settings(
            llm_api_key="k",
            llm_base_url="https://x/v1",
            llm_model="m",
            data_dir=str(tmp_path / "data"),
            extract_enabled=False,
        )
    )
    tool = engine.registry.get("subagent_topology")
    assert tool is not None
    result = tool.execute(child_id="any")
    assert result.status is ToolResultStatus.SUCCESS
    assert "lease: unavailable" in result.content
