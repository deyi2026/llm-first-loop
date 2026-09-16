from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_loop.browser.action import (
    BrowserActionAdapter,
    BrowserActionReceiptStore,
    BrowserDispatchResult,
)
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.builtin.browser_semantic_operation import (
    BrowserSemanticOperationReceiptStore,
    BrowserSemanticOperationTool,
)
from llm_loop.tools.registry import ToolRegistry

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)["base"]


class _Backend:
    def capture(self) -> dict[str, Any]:
        return json.loads(json.dumps(FIXTURE))


class _Actuator:
    def dispatch(self, **_kwargs: Any) -> BrowserDispatchResult:
        return BrowserDispatchResult(
            acknowledged=True,
            boundary_events=(),
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )


def _stack(tmp_path: Path) -> tuple[BrowserSemanticOperationTool, BrowserPerceiveTool]:
    backend = _Backend()
    perception = BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(tmp_path / "perception")
    )
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "actions"),
        capture_backend=backend,
        actuator=_Actuator(),
    )
    semantic_execute = BrowserSemanticExecuteTool(
        perception=perception,
        action_adapter=action,
        session_id_getter=lambda: "s1",
    )
    operation_store = BrowserSemanticOperationReceiptStore(tmp_path / "operation_receipts")
    operation = BrowserSemanticOperationTool(
        perception=perception,
        capture_backend=backend,
        semantic_execute=semantic_execute,
        receipt_store=operation_store,
        session_id_getter=lambda: "s1",
    )
    perceive = BrowserPerceiveTool(
        adapter=perception,
        backend=backend,
        session_id_getter=lambda: "s1",
        exact_ref_hydrator=operation_store.hydrate,
    )
    return operation, perceive


def _provider_do_values() -> set[str]:
    params = BrowserSemanticOperationTool.parameters
    props = params.get("properties") or {}
    if "oneOf" in params:
        variants = params.get("oneOf") or []
    else:
        steps = props.get("steps") or {}
        variants = ((steps.get("items") or {}).get("oneOf") or [])
    values: set[str] = set()
    for branch in variants:
        do_schema = ((branch.get("properties") or {}).get("do") or {})
        values.update(str(item) for item in (do_schema.get("enum") or []))
    return values


def test_mf5_3_perceive_is_the_provider_facing_wait_capability() -> None:
    params = BrowserPerceiveTool.parameters
    props = params["properties"]
    actions = set(props["action"]["enum"])

    assert "wait" in actions
    assert "condition" in props
    assert "within_ms" in props
    # Poll cadence is runtime mechanics, not model task semantics.
    assert "interval_ms" not in props


def test_mf5_3_perceive_wait_contract_covers_page_and_exact_object_conditions() -> None:
    condition = BrowserPerceiveTool.parameters["properties"].get("condition")
    assert isinstance(condition, dict)
    branches = condition.get("oneOf") or []
    kinds = {
        str((((branch.get("properties") or {}).get("kind") or {}).get("enum") or [((branch.get("properties") or {}).get("kind") or {}).get("const") or ""])[0])
        for branch in branches
    }
    assert kinds == {"page_ready", "page_url", "object_state", "object_text"}

    by_kind = {
        str(((branch.get("properties") or {}).get("kind") or {}).get("const")): branch
        for branch in branches
    }
    for kind in ("page_ready", "page_url"):
        props = by_kind[kind]["properties"]
        # The unique host-bound page is a mechanical binding; the model must not invent
        # a document/object identity merely to observe page readiness or URL.
        assert "scope_ref" not in props
        assert "object_ref" not in props
    for kind in ("object_state", "object_text"):
        props = by_kind[kind]["properties"]
        assert "object_ref" in props
        assert "object_ref" in by_kind[kind]["required"]


def test_mf5_3_perceive_page_url_wait_binds_current_host_page(tmp_path: Path) -> None:
    _, perceive = _stack(tmp_path)
    result = perceive.execute(
        action="wait",
        condition={
            "kind": "page_url",
            "match": "equals",
            "url": "https://example.test/a",
        },
        within_ms=50,
    )

    assert result.status.value == "success"
    assert result.tool_name == "browser_perceive"
    payload = json.loads(result.content)
    assert payload["predicate"]["property"] == "url"
    assert payload["predicate"]["value"] == "https://example.test/a"
    assert payload["predicate_result"]["result"] == "satisfied"
    assert payload["predicate_result"]["interval_ms"] == 50


def test_mf5_3_perceive_object_wait_requires_exact_observed_ref(tmp_path: Path) -> None:
    _, perceive = _stack(tmp_path)
    snapshot = json.loads(perceive.execute(action="snapshot").content)
    submit = next(
        obj for obj in snapshot["objects"] if obj.get("attributes", {}).get("name") == "Submit"
    )
    result = perceive.execute(
        action="wait",
        condition={
            "kind": "object_state",
            "object_ref": submit["grounding_ref"],
            "state": "enabled",
            "value": True,
        },
        within_ms=50,
    )

    assert result.status.value == "success"
    assert result.tool_name == "browser_perceive"
    payload = json.loads(result.content)
    assert payload["predicate"]["target"] == submit["id"]
    assert payload["predicate"]["property"] == "enabled"
    assert payload["predicate_result"]["result"] == "satisfied"


def test_mf5_3_perceive_stable_prefix_does_not_teach_low_level_execution_protocol() -> None:
    registry = ToolRegistry()
    registry.register(BrowserPerceiveTool.__new__(BrowserPerceiveTool))
    description = str(registry.schemas(lazy=True)[0]["description"])

    assert "browser_semantic_execute" not in description
    assert "Observe -> Ground -> Execute -> Receipt -> Re-observe/Verify" not in description
    assert "wait" in description.lower()


def test_mf5_3_operate_provider_normal_form_is_one_direct_action() -> None:
    params = BrowserSemanticOperationTool.parameters
    props = params.get("properties") or {}

    assert "steps" not in props
    assert "oneOf" in params
    branches = params["oneOf"]
    assert len(branches) == 5
    assert params.get("additionalProperties") is False


def test_mf5_3_operate_provider_surface_is_mutation_only() -> None:
    provider_verbs = _provider_do_values()
    assert provider_verbs == {"navigate", "click", "set_text", "append_text", "select", "scroll"}
    assert "wait" not in provider_verbs
    assert "wait_text" not in provider_verbs


def test_mf5_3_direct_single_action_executes_without_steps_wrapper(tmp_path: Path) -> None:
    operation, _ = _stack(tmp_path)
    result = operation.execute(
        do="click",
        target={"kind": "button", "name": "Submit"},
    )

    assert result.status.value == "success"
    compact = json.loads(result.content)
    assert compact["status"] == "completed"
    assert compact["task_completion"] == "not_evaluated"
    assert compact["automatic_retry"] is False


def test_mf5_3_compact_action_result_exposes_bounded_delta_sufficiency(tmp_path: Path) -> None:
    operation, _ = _stack(tmp_path)
    # Historical steps wire is deliberately used only to reach the current executor while
    # this RED isolates the missing compact-delta contract from the direct-wire RED above.
    result = operation.execute(
        steps=[{"do": "click", "target": {"kind": "button", "name": "Submit"}}]
    )
    assert result.status.value == "success"
    compact = json.loads(result.content)

    delta = compact.get("delta")
    assert isinstance(delta, dict)
    assert delta["ref"] == compact["diff_ref"]
    assert delta["comparable"] is True
    assert delta["scope_relation"] == "same"
    assert delta["complete"] is True
    assert delta["reasons"] == []
    assert delta["counts"] == {"created": 0, "removed": 0, "changed": 0}
    assert "task_success" not in delta
    assert compact["task_completion"] == "not_evaluated"


def test_mf5_3_compact_delta_is_exactly_hydratable_without_recapture(tmp_path: Path) -> None:
    operation, perceive = _stack(tmp_path)
    compact = json.loads(
        operation.execute(
            steps=[{"do": "click", "target": {"kind": "button", "name": "Submit"}}]
        ).content
    )
    delta = compact.get("delta")
    assert isinstance(delta, dict)

    hydrated = perceive.execute(action="hydrate", grounding_ref=delta["ref"])
    assert hydrated.status.value == "success"
    content = json.loads(hydrated.content)["content"]
    assert content["schema"] == "smc.semantic_diff.v0.1"
    assert content["comparable"] == delta["comparable"]
    assert content["scope_relation"] == delta["scope_relation"]
    assert content["completeness"]["complete"] == delta["complete"]


def test_mf5_3_existing_perception_hydrate_remains_read_only_and_exact(tmp_path: Path) -> None:
    operation, perceive = _stack(tmp_path)
    compact = json.loads(
        operation.execute(
            steps=[{"do": "click", "target": {"kind": "button", "name": "Submit"}}]
        ).content
    )

    hydrated = perceive.execute(action="hydrate", grounding_ref=compact["diff_ref"])
    assert hydrated.status.value == "success"
    payload = json.loads(hydrated.content)
    assert payload["availability"] == "available"
    assert payload["content"]["schema"] == "smc.semantic_diff.v0.1"


def test_mf5_3_cognitive_contract_keeps_program_strategy_authority_closed() -> None:
    wire = json.dumps(
        {
            "perceive": BrowserPerceiveTool.parameters,
            "operate": BrowserSemanticOperationTool.parameters,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    for forbidden in (
        "fuzzy",
        "best_match",
        "auto_target",
        "auto_retry",
        "rebind",
        "latest",
        "task_success",
        "task_complete",
    ):
        assert forbidden not in wire


def test_mf5_3_lazy_perceive_wait_schema_is_self_sufficient_on_first_call() -> None:
    registry = ToolRegistry()
    registry.register(BrowserPerceiveTool.__new__(BrowserPerceiveTool))
    schema = registry.schemas(lazy=True)[0]
    props = (schema.get("parameters") or {}).get("properties") or {}
    condition = props.get("condition") or {}
    branches = condition.get("oneOf") or []
    kinds = {
        str((((branch.get("properties") or {}).get("kind") or {}).get("enum") or [((branch.get("properties") or {}).get("kind") or {}).get("const") or ""])[0])
        for branch in branches
        if isinstance(branch, dict)
    }

    assert kinds == {"page_ready", "page_url", "object_state", "object_text"}
    assert "interval_ms" not in props
