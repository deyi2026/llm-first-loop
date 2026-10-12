from __future__ import annotations

import ast
import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from llm_loop.browser.action import (
    BrowserActionAdapter,
    BrowserActionReceiptStore,
    BrowserDispatchResult,
)
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.semantic_logic import FactGraph, project_document
from llm_loop.tools.builtin.browser_semantic_execute import (
    BrowserSemanticExecuteCompileError,
    BrowserSemanticExecuteTool,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)
MANIFEST = json.loads(
    (ROOT / "docs/SMC-SEMANTIC-LOGIC-P0-FROZEN-FIXTURES-v0.1.json").read_text(
        encoding="utf-8"
    )
)


def _adapter(
    tmp_path: Path,
    *,
    now: list[float] | None = None,
    retention_seconds: int = 60,
) -> BrowserPerceptionAdapter:
    clock = now if now is not None else [1_000.0]
    return BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(
            tmp_path / "browser",
            retention_seconds=retention_seconds,
            now_fn=lambda: clock[0],
        ),
        capture_node_cap=10_000,
    )


def _by_name(result: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [obj for obj in result["objects"] if obj.get("attributes", {}).get("name") == name]
    if len(matches) != 1:
        raise AssertionError(f"expected one object named {name!r}, got {len(matches)}")
    return matches[0]


def _sid(snapshot: dict[str, Any]) -> str:
    return str(snapshot["snapshot"]["snapshot_id"])


def _predicate(
    *, scope_ref: str, target: str, property_name: str, operator: str, value: Any
) -> dict[str, Any]:
    return {
        "schema": "smc.predicate.v0.1",
        "domain": "browser",
        "scope_ref": scope_ref,
        "target": target,
        "property": property_name,
        "operator": operator,
        "value": value,
    }


def _without_submit(*, truncated: bool = False) -> dict[str, Any]:
    raw = deepcopy(FIXTURES["base"])
    for sensor in ("dom", "ax"):
        raw[sensor]["nodes"] = [
            node for node in raw[sensor]["nodes"] if node.get("physical_id") != "n-submit"
        ]
    if truncated:
        raw["dom"]["truncated"] = True
    return raw


def _snapshot_local_ax_fixture() -> dict[str, Any]:
    raw = deepcopy(FIXTURES["base"])
    raw["ax"]["nodes"].append(
        {
            "ax_id": "ax-local-only",
            "physical_id": None,
            "frame_token": None,
            "kind": "text",
            "attributes": {"role": "InlineTextBox", "name": "Local only"},
            "state": {"exists": True},
        }
    )
    return raw


def _compile_tool(adapter: BrowserPerceptionAdapter) -> BrowserSemanticExecuteTool:
    return BrowserSemanticExecuteTool(
        perception=adapter,
        action_adapter=object(),  # type: ignore[arg-type] - compile-only P1-A fixture path
        session_id_getter=lambda: "s1",
    )


class _CaptureBackend:
    def __init__(self, captures: list[dict[str, Any]]) -> None:
        self.captures = [deepcopy(item) for item in captures]
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        if not self.captures:
            raise RuntimeError("no capture")
        if len(self.captures) == 1:
            return deepcopy(self.captures[0])
        return deepcopy(self.captures.pop(0))


class _Actuator:
    def __init__(self, result: BrowserDispatchResult | Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = result or BrowserDispatchResult(
            acknowledged=True,
            boundary_events=(),
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )

    def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _action_stack(
    tmp_path: Path,
    captures: list[dict[str, Any]],
    *,
    actuator: _Actuator | None = None,
) -> tuple[
    BrowserPerceptionAdapter,
    BrowserActionReceiptStore,
    _CaptureBackend,
    _Actuator,
    BrowserActionAdapter,
]:
    perception = BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(tmp_path / "perception")
    )
    receipts = BrowserActionReceiptStore(tmp_path / "actions")
    backend = _CaptureBackend(captures)
    actual_actuator = actuator or _Actuator()
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=receipts,
        capture_backend=backend,
        actuator=actual_actuator,
    )
    return perception, receipts, backend, actual_actuator, action


def _click_action(first: dict[str, Any], *, action_id: str = "act-1") -> dict[str, Any]:
    target = _by_name(first, "Submit")
    return {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": target["scope_ref"],
        "action_id": action_id,
        "verb": "click",
        "target_id": target["id"],
        "args": {},
        "args_normalization": {"applied": False, "rule": None},
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": first["snapshot"]["snapshot_id"],
        "version_scope": "object",
        "version_precondition": "required",
    }


def _case_s1_object(tmp_path: Path) -> dict[str, Any]:
    adapter = _adapter(tmp_path)
    snap = adapter.snapshot("s1", FIXTURES["base"])
    target = _by_name(snap, "Submit")
    compiled = _compile_tool(adapter).compile_request(
        "s1", {"verb": "click", "target_ref": target["grounding_ref"], "args": {}}
    )
    return {"target": target, "compiled": compiled}


def _case_s1_resource(tmp_path: Path) -> dict[str, Any]:
    adapter = _adapter(tmp_path)
    snap = adapter.snapshot("s1", FIXTURES["base"])
    resource_ref = str(snap["resource_ref"])
    hydrated = adapter.hydrate("s1", resource_ref)
    compiled = _compile_tool(adapter).compile_request(
        "s1",
        {
            "verb": "navigate",
            "target_ref": resource_ref,
            "args": {"url": "http://127.0.0.1/example"},
        },
    )
    return {"resource_ref": resource_ref, "hydrated": hydrated, "compiled": compiled}


def _case_s1_fail_closed(tmp_path: Path) -> dict[str, Any]:
    now = [1_000.0]
    adapter = _adapter(tmp_path, now=now, retention_seconds=10)
    snap = adapter.snapshot("s1", FIXTURES["base"])
    target_ref = str(_by_name(snap, "Submit")["grounding_ref"])
    unauthorized = adapter.hydrate("other-session", target_ref)
    wrong_projection = ""
    try:
        _compile_tool(adapter).compile_request(
            "s1", {"verb": "navigate", "target_ref": target_ref, "args": {"url": "http://127.0.0.1/"}}
        )
    except BrowserSemanticExecuteCompileError as exc:
        wrong_projection = str(exc)
    now[0] = 1_011.0
    expired = adapter.hydrate("s1", target_ref)
    return {
        "unauthorized": unauthorized,
        "wrong_projection_error": wrong_projection,
        "expired": expired,
        "dispatch_count": 0,
    }


def _case_s2_conflict(tmp_path: Path) -> dict[str, Any]:
    return _adapter(tmp_path).snapshot("s1", FIXTURES["conflict"])


def _case_s2_fusion(tmp_path: Path) -> dict[str, Any]:
    return _adapter(tmp_path).snapshot("s1", FIXTURES["fusion_ambiguity"])


def _case_s3_absence(tmp_path: Path) -> dict[str, Any]:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    submit = _by_name(before, "Submit")
    predicate = _predicate(
        scope_ref=str(submit["scope_ref"]),
        target=str(submit["id"]),
        property_name="exists",
        operator="eq",
        value=False,
    )
    complete_after = adapter.snapshot("s1", _without_submit())
    complete = adapter.evaluate_predicate("s1", _sid(complete_after), predicate)
    partial_after = adapter.snapshot("s1", _without_submit(truncated=True))
    partial = adapter.evaluate_predicate("s1", _sid(partial_after), predicate)
    return {"predicate": predicate, "complete": complete, "partial": partial}


def _case_s3_unknown(tmp_path: Path) -> dict[str, Any]:
    adapter = _adapter(tmp_path)
    first = adapter.snapshot("s1", _snapshot_local_ax_fixture())
    local = _by_name(first, "Local only")
    second = adapter.snapshot("s1", _snapshot_local_ax_fixture())
    local_predicate = _predicate(
        scope_ref=str(local["scope_ref"]),
        target=str(local["id"]),
        property_name="exists",
        operator="eq",
        value=False,
    )
    invented_predicate = {**local_predicate, "target": "el_00000000000000000000"}
    stable_submit = _by_name(second, "Submit")
    unobserved_predicate = _predicate(
        scope_ref=str(stable_submit["scope_ref"]),
        target=str(stable_submit["id"]),
        property_name="focused",
        operator="eq",
        value=True,
    )
    return {
        "local": adapter.evaluate_predicate("s1", _sid(second), local_predicate),
        "invented": adapter.evaluate_predicate("s1", _sid(second), invented_predicate),
        "unobserved": adapter.evaluate_predicate("s1", _sid(second), unobserved_predicate),
    }


def _case_s3_lower_bound(tmp_path: Path) -> dict[str, Any]:
    adapter = _adapter(tmp_path)
    raw = deepcopy(FIXTURES["base"])
    raw["dom"]["truncated"] = True
    snap = adapter.snapshot("s1", raw)
    scope_ref = str(snap["snapshot"]["scope"]["scope_ref"])
    at_least_one = _predicate(
        scope_ref=scope_ref,
        target=scope_ref,
        property_name="object_count",
        operator="ge",
        value=1,
    )
    at_most_many = {**at_least_one, "operator": "le", "value": 999}
    return {
        "positive": adapter.evaluate_predicate("s1", _sid(snap), at_least_one),
        "non_decisive": adapter.evaluate_predicate("s1", _sid(snap), at_most_many),
    }


def _object_version_case(
    tmp_path: Path, *, after_fixture: dict[str, Any]
) -> dict[str, Any]:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    target = _by_name(before, "Submit")
    after = adapter.snapshot("s1", after_fixture)
    return adapter.assess_version_precondition(
        "s1",
        expected_version=_sid(before),
        observed_version=_sid(after),
        version_scope="object",
        scope_ref=str(target["scope_ref"]),
        target_id=str(target["id"]),
    )


def _case_s4_changed(tmp_path: Path) -> dict[str, Any]:
    changed = deepcopy(FIXTURES["base"])
    for source in ("dom", "ax"):
        for node in changed[source]["nodes"]:
            if node.get("physical_id") == "n-submit":
                node.setdefault("state", {})["enabled"] = False
    return _object_version_case(tmp_path, after_fixture=changed)


def _case_s4_unchanged(tmp_path: Path) -> dict[str, Any]:
    return _object_version_case(tmp_path, after_fixture=FIXTURES["reorder"])


def _case_s4_document_change(tmp_path: Path) -> dict[str, Any]:
    return _object_version_case(tmp_path, after_fixture=FIXTURES["navigate"])


def _case_s4_incomplete_or_expired(tmp_path: Path) -> dict[str, Any]:
    adapter = _adapter(tmp_path / "partial")
    before = adapter.snapshot("s1", FIXTURES["base"])
    target = _by_name(before, "Submit")
    partial_raw = _without_submit(truncated=True)
    after = adapter.snapshot("s1", partial_raw)
    partial = adapter.assess_version_precondition(
        "s1",
        expected_version=_sid(before),
        observed_version=_sid(after),
        version_scope="object",
        scope_ref=str(target["scope_ref"]),
        target_id=str(target["id"]),
    )

    now = [1_000.0]
    expiry_adapter = _adapter(tmp_path / "expired", now=now, retention_seconds=10)
    old = expiry_adapter.snapshot("s1", FIXTURES["base"])
    now[0] = 1_005.0
    current = expiry_adapter.snapshot("s1", FIXTURES["push_state"])
    now[0] = 1_011.0
    expired = expiry_adapter.assess_version_precondition(
        "s1",
        expected_version=_sid(old),
        observed_version=_sid(current),
        version_scope="snapshot",
        scope_ref=str(old["snapshot"]["scope"]["scope_ref"]),
    )
    return {"partial": partial, "expired": expired}


def _case_s5_running_terminal(tmp_path: Path) -> dict[str, Any]:
    perception, receipts, backend, actuator, action = _action_stack(
        tmp_path, [FIXTURES["base"]]
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first))
    return {
        "result": result,
        "receipts": receipts.list_action("s1", "act-1"),
        "dispatch_count": len(actuator.calls),
        "capture_count": backend.calls,
    }


def _case_s5_duplicate(tmp_path: Path) -> dict[str, Any]:
    perception, receipts, backend, actuator, action = _action_stack(
        tmp_path, [FIXTURES["base"]]
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    request = _click_action(first)
    first_result = action.execute("s1", request)
    duplicate = action.execute("s1", request)
    return {
        "first": first_result,
        "duplicate": duplicate,
        "receipts": receipts.list_action("s1", "act-1"),
        "dispatch_count": len(actuator.calls),
        "capture_count": backend.calls,
    }


def _case_s5_transport_ambiguity(tmp_path: Path) -> dict[str, Any]:
    changed = deepcopy(FIXTURES["base"])
    for source in ("dom", "ax"):
        for node in changed[source]["nodes"]:
            if node.get("physical_id") == "n-submit":
                node.setdefault("state", {})["enabled"] = False
    perception, receipts, backend, actuator, action = _action_stack(
        tmp_path,
        [FIXTURES["base"], changed],
        actuator=_Actuator(TimeoutError("ack lost after dispatch")),
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first, action_id="partial-effect"))
    return {
        "result": result,
        "receipts": receipts.list_action("s1", "partial-effect"),
        "dispatch_count": len(actuator.calls),
        "capture_count": backend.calls,
    }


CaseBuilder = Callable[[Path], dict[str, Any]]

CASE_BUILDERS: dict[str, CaseBuilder] = {
    "S1-object-grounding-compile": _case_s1_object,
    "S1-resource-grounding-compile": _case_s1_resource,
    "S1-grounding-fail-closed": _case_s1_fail_closed,
    "S2-dom-ax-field-conflict": _case_s2_conflict,
    "S2-identity-fusion-ambiguity": _case_s2_fusion,
    "S3-absence-complete-vs-partial": _case_s3_absence,
    "S3-unknown-or-unstable-identity": _case_s3_unknown,
    "S3-lower-bound-object-count": _case_s3_lower_bound,
    "S4-object-same-generation-changed": _case_s4_changed,
    "S4-object-unchanged-new-observation": _case_s4_unchanged,
    "S4-document-generation-change": _case_s4_document_change,
    "S4-incomplete-missing-target": _case_s4_incomplete_or_expired,
    "S5-running-terminal-sequence": _case_s5_running_terminal,
    "S5-duplicate-action-id": _case_s5_duplicate,
    "S5-transport-ambiguity-no-replay": _case_s5_transport_ambiguity,
}


def _manifest_cases() -> list[tuple[str, str]]:
    return [
        (str(gate["gate_id"]), str(case["fixture_id"]))
        for gate in MANIFEST["gates"]
        for case in gate["cases"]
    ]


def test_p1a_builder_set_exactly_matches_all_15_frozen_cases() -> None:
    frozen = _manifest_cases()
    assert len(frozen) == 15
    assert len({fixture_id for _, fixture_id in frozen}) == 15
    assert set(CASE_BUILDERS) == {fixture_id for _, fixture_id in frozen}


@pytest.mark.parametrize(("gate_id", "fixture_id"), _manifest_cases())
def test_all_frozen_cases_project_losslessly_to_typed_fact_graph(
    tmp_path: Path, gate_id: str, fixture_id: str
) -> None:
    canonical = CASE_BUILDERS[fixture_id](tmp_path / fixture_id)
    graph = project_document(
        graph_id=fixture_id,
        document=canonical,
        domain="browser",
        source_ref=f"python_oracle:{gate_id}:{fixture_id}",
    )

    assert isinstance(graph, FactGraph)
    assert graph.authority == "shadow_only"
    assert graph.production_consumed is False
    assert graph.domain == "browser"
    assert graph.reconstruct() == canonical
    assert graph.facts or graph.containers
    assert len({fact.fact_id for fact in graph.facts}) == len(graph.facts)
    assert len({fact.path for fact in graph.facts}) == len(graph.facts)
    assert all(fact.provenance.kind == "oracle_projection" for fact in graph.facts)


def test_projection_is_deterministic_for_same_concrete_oracle_document(tmp_path: Path) -> None:
    canonical = _case_s2_conflict(tmp_path)
    first = project_document(
        graph_id="S2-dom-ax-field-conflict",
        document=canonical,
        domain="browser",
        source_ref="python_oracle:S2",
    )
    second = project_document(
        graph_id="S2-dom-ax-field-conflict",
        document=canonical,
        domain="browser",
        source_ref="python_oracle:S2",
    )
    assert first.to_dict() == second.to_dict()
    assert first.structural_fingerprint() == second.structural_fingerprint()


def test_conflict_projection_preserves_source_and_grounding_provenance(tmp_path: Path) -> None:
    canonical = _case_s2_conflict(tmp_path)
    graph = project_document(
        graph_id="S2-dom-ax-field-conflict",
        document=canonical,
        domain="browser",
        source_ref="python_oracle:S2",
    )
    conflict_facts = [
        fact
        for fact in graph.facts
        if any(segment == "observations" for segment in fact.path)
    ]
    sources = {fact.provenance.source for fact in conflict_facts}
    grounding = {fact.provenance.grounding_ref for fact in conflict_facts if fact.provenance.grounding_ref}
    assert {"dom", "ax"} <= sources
    assert len(grounding) >= 2
    assert graph.reconstruct() == canonical


def test_ir_preserves_empty_containers_and_json_scalar_types() -> None:
    canonical = {
        "empty_object": {},
        "empty_array": [],
        "null": None,
        "boolean": False,
        "integer": 1,
        "number": 1.5,
        "string": "x",
        "nested": [{"items": []}],
    }
    graph = project_document(
        graph_id="shape-probe",
        document=canonical,
        domain="test",
        source_ref="python_oracle:shape-probe",
    )
    assert graph.reconstruct() == canonical
    observed_types = {fact.value_type for fact in graph.facts}
    assert {"null", "boolean", "integer", "number", "string"} <= observed_types


def test_p1a_has_no_production_consumer_imports() -> None:
    semantic_root = (ROOT / "src/llm_loop/semantic_logic").resolve()
    offenders: list[str] = []
    for path in (ROOT / "src/llm_loop").rglob("*.py"):
        if semantic_root in path.resolve().parents:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and str(node.module or "").startswith(
                "llm_loop.semantic_logic"
            ):
                offenders.append(str(path.relative_to(ROOT)))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("llm_loop.semantic_logic"):
                        offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_projection_rejects_non_json_values_and_non_finite_numbers() -> None:
    with pytest.raises(TypeError, match="non-JSON"):
        project_document(
            graph_id="bad-set",
            document={"x": {1, 2}},
            domain="test",
            source_ref="python_oracle:bad",
        )
    with pytest.raises(ValueError, match="non-finite"):
        project_document(
            graph_id="bad-nan",
            document={"x": float("nan")},
            domain="test",
            source_ref="python_oracle:bad",
        )
