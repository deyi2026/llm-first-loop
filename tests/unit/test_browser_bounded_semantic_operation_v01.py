from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_loop.browser.action import (
    BrowserActionAdapter,
    BrowserActionReceiptStore,
    BrowserDispatchResult,
)
from llm_loop.browser.perception import (
    SEMANTIC_OBJECT_KINDS,
    BrowserPerceptionAdapter,
    BrowserPerceptionStore,
)
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.builtin.browser_semantic_operation import BrowserSemanticOperationTool
from llm_loop.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads((ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text())


class _Backend:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = json.loads(json.dumps(raw))
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        return json.loads(json.dumps(self.raw))


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


def _stack(tmp_path: Path, raw: dict[str, Any] | None = None):
    resolved_raw = raw if raw is not None else FIXTURES["base"]
    assert isinstance(resolved_raw, dict)
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    backend = _Backend(resolved_raw)
    actuator = _Actuator()
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "actions"),
        capture_backend=backend,
        actuator=actuator,
    )
    execute = BrowserSemanticExecuteTool(
        perception=perception,
        action_adapter=action,
        session_id_getter=lambda: "s1",
    )
    operation = BrowserSemanticOperationTool(
        perception=perception,
        capture_backend=backend,
        semantic_execute=execute,
        session_id_getter=lambda: "s1",
    )
    return operation, actuator


def _receipt(result):
    assert result.status.value == "success"
    return json.loads(result.content)


def test_exact_unique_identity_dispatches_once_and_never_claims_task_completion(tmp_path: Path) -> None:
    tool, actuator = _stack(tmp_path)
    result = tool.execute(
        clauses=[
            {
                "kind": "mutate",
                "verb": "click",
                "target": {"kind": "object", "identity": {"kind": "button", "name": "Submit"}},
                "args": {},
            }
        ]
    )
    receipt = _receipt(result)
    assert receipt["execution_status"] == "clauses_exhausted"
    assert receipt["task_completion"] == "not_evaluated"
    assert len(actuator.calls) == 1
    assert actuator.calls[0]["verb"] == "click"
    assert receipt["clauses"][0]["exact_match_count"] == 1
    assert receipt["clauses"][0]["action_receipt"]["status"] == "ok"
    assert receipt["retry"]["automatic_retry_performed"] is False


def test_zero_exact_matches_halts_before_dispatch(tmp_path: Path) -> None:
    tool, actuator = _stack(tmp_path)
    receipt = _receipt(
        tool.execute(
            clauses=[
                {
                    "kind": "mutate",
                    "verb": "click",
                    "target": {"kind": "object", "identity": {"kind": "button", "name": "Missing"}},
                    "args": {},
                }
            ]
        )
    )
    assert receipt["execution_status"] == "halted"
    assert receipt["halt_reason"] == "exact_identity_match_count:0"
    assert actuator.calls == []


def test_ambiguous_exact_matches_halt_without_best_match(tmp_path: Path) -> None:
    raw = json.loads(json.dumps(FIXTURES["base"]))
    source = next(n for n in raw["dom"]["nodes"] if n.get("attributes", {}).get("name") == "Submit")
    clone = json.loads(json.dumps(source))
    clone["physical_id"] = "second-submit"
    raw["dom"]["nodes"].append(clone)
    tool, actuator = _stack(tmp_path, raw)
    receipt = _receipt(
        tool.execute(
            clauses=[
                {
                    "kind": "mutate",
                    "verb": "click",
                    "target": {"kind": "object", "identity": {"kind": "button", "name": "Submit"}},
                    "args": {},
                }
            ]
        )
    )
    assert receipt["execution_status"] == "halted"
    assert receipt["halt_reason"].startswith("exact_identity_match_count:")
    assert receipt["halt_reason"] != "exact_identity_match_count:1"
    assert actuator.calls == []


def test_model_declared_wait_then_mutation_reuses_typed_predicate_engine(tmp_path: Path) -> None:
    tool, actuator = _stack(tmp_path)
    receipt = _receipt(
        tool.execute(
            clauses=[
                {
                    "kind": "wait",
                    "target": {"kind": "object", "identity": {"kind": "button", "name": "Submit"}},
                    "property": "enabled",
                    "operator": "eq",
                    "value": True,
                    "timeout_ms": 100,
                    "interval_ms": 10,
                },
                {
                    "kind": "mutate",
                    "verb": "click",
                    "target": {"kind": "object", "identity": {"kind": "button", "name": "Submit"}},
                    "args": {},
                },
            ]
        )
    )
    assert receipt["execution_status"] == "clauses_exhausted"
    assert receipt["clauses"][0]["predicate_result"]["result"] == "satisfied"
    assert len(actuator.calls) == 1


def test_model_declared_sequence_can_navigate_then_exact_ground_object(tmp_path: Path) -> None:
    tool, actuator = _stack(tmp_path)
    receipt = _receipt(
        tool.execute(
            clauses=[
                {
                    "kind": "mutate",
                    "verb": "navigate",
                    "target": {"kind": "page"},
                    "args": {"url": "http://127.0.0.1:7777/"},
                },
                {
                    "kind": "mutate",
                    "verb": "click",
                    "target": {"kind": "object", "identity": {"kind": "button", "name": "Submit"}},
                    "args": {},
                },
            ]
        )
    )
    assert receipt["execution_status"] == "clauses_exhausted"
    assert [call["verb"] for call in actuator.calls] == ["navigate", "click"]
    assert receipt["task_completion"] == "not_evaluated"


def test_model_surface_is_closed_and_carries_no_policy_authority() -> None:
    schema = BrowserSemanticOperationTool._CLAUSE_PARAMETERS
    assert schema["additionalProperties"] is False
    assert schema["properties"]["clauses"]["maxItems"] == 8
    variants = schema["properties"]["clauses"]["items"]["oneOf"]
    assert len(variants) == 6
    assert all(variant["additionalProperties"] is False for variant in variants)
    wire = json.dumps(schema, sort_keys=True)
    for forbidden in ("fuzzy", "best_match", "retry", "task_complete", "task_success", "latest"):
        assert forbidden not in wire


def test_provider_schema_is_recursively_closed_and_verb_specific() -> None:
    schema = BrowserSemanticOperationTool._CLAUSE_PARAMETERS

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(schema)
    branches = schema["properties"]["clauses"]["items"]["oneOf"]
    mutate = {
        branch["properties"]["verb"].get("const"): branch
        for branch in branches
        if branch["properties"].get("kind", {}).get("const") == "mutate"
    }
    assert set(mutate) == {"click", "fill", "select", "scroll", "navigate"}
    assert mutate["click"]["properties"]["args"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    assert set(mutate["fill"]["properties"]["args"]["required"]) == {"text", "mode"}
    assert mutate["fill"]["properties"]["args"]["properties"]["mode"]["enum"] == [
        "replace",
        "append",
    ]
    assert mutate["select"]["properties"]["args"]["required"] == ["value"]
    assert mutate["scroll"]["properties"]["args"]["required"] == ["delta_pages"]
    assert mutate["navigate"]["properties"]["args"]["required"] == ["url"]


def test_identity_kind_schema_reuses_canonical_semantic_object_vocabulary() -> None:
    schema = BrowserSemanticOperationTool._CLAUSE_PARAMETERS
    branches = schema["properties"]["clauses"]["items"]["oneOf"]
    object_kind_enums: list[list[str]] = []
    for branch in branches:
        target = branch["properties"].get("target")
        if not isinstance(target, dict):
            continue
        identity = (target.get("properties") or {}).get("identity")
        if not isinstance(identity, dict):
            continue
        object_kind_enums.append(identity["properties"]["kind"]["enum"])

    assert object_kind_enums
    assert all(tuple(enum) == SEMANTIC_OBJECT_KINDS for enum in object_kind_enums)
    assert "input" in SEMANTIC_OBJECT_KINDS
    assert "textbox" not in SEMANTIC_OBJECT_KINDS


def test_lazy_provider_surface_preserves_bounded_operation_first_call_contract() -> None:
    reg = ToolRegistry()
    reg.register(BrowserSemanticOperationTool.__new__(BrowserSemanticOperationTool))
    params = BrowserSemanticOperationTool._CLAUSE_LAZY_PARAMETERS

    assert params["additionalProperties"] is False
    clauses = params["properties"]["clauses"]
    assert clauses["type"] == "array"
    assert clauses["minItems"] == 1
    assert clauses["maxItems"] == 8
    assert clauses["description"] == (
        "Exact clause fields: mutate={kind,verb,target,args}; "
        "wait={kind,target,property,operator,value,timeout_ms,interval_ms}; "
        "wait has no verb/args."
    )
    branches = clauses["items"]["oneOf"]
    assert len(branches) == 3
    assert all(branch["additionalProperties"] is False for branch in branches)
    assert all("const" not in json.dumps(branch, sort_keys=True) for branch in branches)

    object_mutation = next(
        branch
        for branch in branches
        if set(branch["properties"].get("verb", {}).get("enum") or [])
        == {"click", "fill", "select", "scroll"}
    )
    assert object_mutation["properties"]["kind"]["enum"] == ["mutate"]
    assert len(object_mutation["properties"]["args"]["anyOf"]) == 4
    navigate = next(
        branch
        for branch in branches
        if branch["properties"].get("verb", {}).get("enum") == ["navigate"]
    )
    assert navigate["properties"]["target"]["properties"]["kind"]["enum"] == ["page"]
    wait = next(
        branch for branch in branches if branch["properties"]["kind"]["enum"] == ["wait"]
    )
    assert "verb" not in wait["properties"]
    identity_kind = (
        object_mutation["properties"]["target"]["properties"]["identity"]["properties"]["kind"]
    )
    assert tuple(identity_kind["enum"]) == SEMANTIC_OBJECT_KINDS
