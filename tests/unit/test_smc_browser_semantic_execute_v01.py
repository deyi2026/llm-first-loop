from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from llm_loop.browser.action import (
    BrowserActionAdapter,
    BrowserActionReceiptStore,
    BrowserDispatchResult,
)
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_semantic_execute import (
    BrowserSemanticExecuteCompileError,
    BrowserSemanticExecuteTool,
)
from llm_loop.tools.registry import _COMPACT_TOOL_DESCRIPTIONS

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)


def _by_name(result: dict[str, Any], name: str) -> dict[str, Any]:
    return next(obj for obj in result["objects"] if obj.get("attributes", {}).get("name") == name)


class _CaptureBackend:
    def __init__(self, capture: dict[str, Any]) -> None:
        self.capture_value = json.loads(json.dumps(capture))
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        return json.loads(json.dumps(self.capture_value))


class _Actuator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
        self.calls.append(kwargs)
        return BrowserDispatchResult(
            acknowledged=True,
            boundary_events=(),
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )


def _stack(tmp_path: Path):
    perception = BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(tmp_path / "perception")
    )
    backend = _CaptureBackend(FIXTURES["base"])
    actuator = _Actuator()
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "actions"),
        capture_backend=backend,
        actuator=actuator,
    )
    tool = BrowserSemanticExecuteTool(
        perception=perception,
        action_adapter=action,
        session_id_getter=lambda: "s1",
    )
    return perception, backend, actuator, action, tool


def test_snapshot_exposes_exact_resource_ref_that_hydrates_session_scoped(tmp_path: Path) -> None:
    perception = BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(tmp_path / "perception")
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    resource_ref = first["resource_ref"]
    snapshot_id = first["snapshot"]["snapshot_id"]
    assert resource_ref == f"grounding://browser/v0.1/{snapshot_id}/resource/page"

    hydrated = perception.hydrate("s1", resource_ref)
    assert hydrated["availability"] == "available"
    content = hydrated["content"]
    assert content == {
        "schema": "smc.browser_resource_grounding.v0.1",
        "domain": "browser",
        "kind": "page",
        "scope_ref": next(x["scope_ref"] for x in first["scope_facts"] if x["kind"] == "page"),
        "grounding_ref": resource_ref,
        "observed_version": snapshot_id,
    }
    assert perception.hydrate("other-session", resource_ref)["availability"] == "unauthorized"


def test_compiler_derives_object_action_from_exact_grounding_ref_only(tmp_path: Path) -> None:
    perception, _, _, _, tool = _stack(tmp_path)
    first = perception.snapshot("s1", FIXTURES["base"])
    target = _by_name(first, "Submit")
    request = {"verb": "click", "target_ref": target["grounding_ref"], "args": {}}

    compiled = tool.compile_request("s1", request)
    assert compiled == {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": target["scope_ref"],
        "action_id": compiled["action_id"],
        "verb": "click",
        "target_id": target["id"],
        "args": {},
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": first["snapshot"]["snapshot_id"],
        "version_scope": "object",
        "version_precondition": "required",
    }
    assert compiled["action_id"].startswith("sact-")
    assert tool.compile_request("s1", request)["action_id"] == compiled["action_id"]


def test_compiler_derives_navigation_from_resource_ref(tmp_path: Path) -> None:
    perception, _, _, _, tool = _stack(tmp_path)
    first = perception.snapshot("s1", FIXTURES["base"])
    compiled = tool.compile_request(
        "s1",
        {
            "verb": "navigate",
            "target_ref": first["resource_ref"],
            "args": {"url": "http://127.0.0.1/example"},
        },
    )
    page_scope = next(x["scope_ref"] for x in first["scope_facts"] if x["kind"] == "page")
    assert compiled["scope_ref"] == page_scope
    assert compiled["target_id"] == page_scope
    assert compiled["expected_version"] == first["snapshot"]["snapshot_id"]
    assert compiled["version_scope"] == "resource"


def test_execute_preserves_single_dispatch_and_dedups_same_exact_request(tmp_path: Path) -> None:
    perception, backend, actuator, _, tool = _stack(tmp_path)
    first = perception.snapshot("s1", FIXTURES["base"])
    target = _by_name(first, "Submit")
    request = {"verb": "click", "target_ref": target["grounding_ref"], "args": {}}

    receipt1 = tool.execute_request("s1", request)
    receipt2 = tool.execute_request("s1", request)
    assert receipt1["status"] == "ok"
    assert receipt2["status"] == "rejected"
    assert receipt2["completeness"]["reasons"] == ["duplicate_action_id"]
    assert len(actuator.calls) == 1
    assert backend.calls == 2  # first execution pre/post observations; duplicate stops before recapture


def test_compiler_rejects_cross_session_and_wrong_projection_without_dispatch(tmp_path: Path) -> None:
    perception, backend, actuator, _, tool = _stack(tmp_path)
    first = perception.snapshot("s1", FIXTURES["base"])
    target = _by_name(first, "Submit")

    with pytest.raises(BrowserSemanticExecuteCompileError, match="target_ref_unauthorized:session_scope"):
        tool.compile_request("s2", {"verb": "click", "target_ref": target["grounding_ref"], "args": {}})
    with pytest.raises(BrowserSemanticExecuteCompileError, match="target_ref_projection_mismatch"):
        tool.compile_request("s1", {"verb": "click", "target_ref": first["resource_ref"], "args": {}})
    with pytest.raises(BrowserSemanticExecuteCompileError, match="target_ref_projection_mismatch"):
        tool.compile_request(
            "s1",
            {"verb": "navigate", "target_ref": target["grounding_ref"], "args": {"url": "http://127.0.0.1/"}},
        )
    assert backend.calls == 0
    assert actuator.calls == []


def test_semantic_execute_tool_surface_exposes_only_model_owned_choices() -> None:
    assert BrowserSemanticExecuteTool.name == "browser_semantic_execute"
    assert set(BrowserSemanticExecuteTool.parameters["properties"]) == {"verb", "target_ref", "args"}
    assert set(BrowserSemanticExecuteTool.parameters["required"]) == {"verb", "target_ref", "args"}
    assert BrowserSemanticExecuteTool.parameters["additionalProperties"] is False
    for hidden_mechanical_field in (
        "schema",
        "domain",
        "scope_ref",
        "action_id",
        "target_id",
        "expected_version",
        "version_scope",
        "operation_class",
        "idempotency_class",
        "atomicity_class",
        "version_precondition",
    ):
        assert hidden_mechanical_field not in BrowserSemanticExecuteTool.parameters["properties"]
    description = BrowserSemanticExecuteTool.description
    for marker in (
        "snapshot",
        "GroundingRef",
        "browser_semantic_execute",
        "ActionReceipt",
        "Re-observe",
        "不自动选择目标",
        "不自动 retry",
        "不自动 rebind",
        "不判断任务完成",
    ):
        assert marker in description


def test_semantic_execute_compact_description_teaches_the_minimum_call_path() -> None:
    compact = _COMPACT_TOOL_DESCRIPTIONS["browser_semantic_execute"]
    for marker in (
        "snapshot",
        "GroundingRef",
        "target_ref",
        "resource_ref",
        "click={}",
        "fill={text,mode(replace|append)}",
        "select={value}",
        "navigate={url}",
        "scroll={delta_pages}",
        "ActionReceipt",
        "再 snapshot",
        "不自动 retry/rebind",
        "不等于任务完成",
    ):
        assert marker in compact

    from llm_loop.tools.registry import ToolRegistry

    reg = ToolRegistry()
    reg.register(
        BrowserSemanticExecuteTool(
            perception=object(),  # type: ignore[arg-type]
            action_adapter=object(),  # type: ignore[arg-type]
            session_id_getter=lambda: "s1",
        )
    )
    lazy = reg.schemas(lazy=True)[0]
    assert "SemanticObject.grounding_ref" in lazy["parameters"]["properties"]["target_ref"]["description"]
    assert "resource_ref" in lazy["parameters"]["properties"]["target_ref"]["description"]
    assert "fill={text,mode}" in lazy["parameters"]["properties"]["args"]["description"]
