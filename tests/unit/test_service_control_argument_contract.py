from __future__ import annotations

from llm_loop.core.message import ToolResultStatus
from llm_loop.runtime.service_control import ManagedServiceDeploymentStore
from llm_loop.tools.builtin.service_control import ServiceControlTool
from llm_loop.tools.registry import ToolRegistry


def _tool(tmp_path):
    spawned: list[str] = []
    store = ManagedServiceDeploymentStore(tmp_path / "data")
    tool = ServiceControlTool(store=store, worker_spawner=spawned.append)
    return tool, store, spawned


def test_existing_lazy_schema_keeps_restart_target_enum_without_extra_override() -> None:
    lazy = ToolRegistry._lazy_schema_skeleton(ServiceControlTool.parameters)

    assert not hasattr(ServiceControlTool, "lazy_parameters")
    assert lazy["properties"]["target"]["enum"] == [
        "web",
        "feishu",
        "learning",
        "all",
    ]


def test_verify_acknowledge_reports_all_missing_fields_in_one_preflight(tmp_path) -> None:
    tool, store, spawned = _tool(tmp_path)

    result = tool.execute(
        action="verify_acknowledge",
        action_id="svc-x",
        verdict="accept",
    )

    assert result.status == ToolResultStatus.FAILURE
    assert "missing=evidence,reason" in result.content
    assert "get_tool_schema(service_control)" in result.content
    assert spawned == []
    assert store.read_action("svc-x") is None


def test_restart_invalid_target_fails_before_accept_or_spawn(tmp_path) -> None:
    tool, store, spawned = _tool(tmp_path)

    result = tool.execute(action="restart", target="web+feishu")

    assert result.status == ToolResultStatus.FAILURE
    assert "target='web+feishu'" in result.content
    assert "web" in result.content and "feishu" in result.content
    assert spawned == []
    assert list(store.actions_dir.glob("*.json")) == []


def test_verify_contract_rejects_invalid_verdict_and_missing_evidence_together(tmp_path) -> None:
    tool, _store, spawned = _tool(tmp_path)

    result = tool.execute(
        action="verify_acknowledge",
        action_id="svc-x",
        verdict="done",
        reason="operator reviewed evidence",
    )

    assert result.status == ToolResultStatus.FAILURE
    assert "missing=evidence" in result.content
    assert "verdict='done'" in result.content
    assert spawned == []
