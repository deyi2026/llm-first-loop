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
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.builtin.browser_semantic_operation import (
    BrowserSemanticOperationReceiptStore,
    BrowserSemanticOperationTool,
)

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
    def __init__(self, *, boundary_events: tuple[dict[str, Any], ...] = ()) -> None:
        self.calls: list[dict[str, Any]] = []
        self.boundary_events = boundary_events

    def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
        self.calls.append(kwargs)
        return BrowserDispatchResult(
            acknowledged=True,
            boundary_events=self.boundary_events,
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )


def _stack(
    tmp_path: Path,
    *,
    raw: dict[str, Any] | None = None,
    boundary_events: tuple[dict[str, Any], ...] = (),
):
    resolved_raw = raw if raw is not None else FIXTURES["base"]
    assert isinstance(resolved_raw, dict)
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    backend = _Backend(resolved_raw)
    actuator = _Actuator(boundary_events=boundary_events)
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
        receipt_store=BrowserSemanticOperationReceiptStore(tmp_path / "operation_receipts"),
        session_id_getter=lambda: "s1",
    )
    return operation, actuator


def _json_result(result: Any) -> dict[str, Any]:
    assert result.status.value == "success"
    return json.loads(result.content)


def test_mf1_short_wire_accepts_navigation_without_protocol_scaffolding(tmp_path: Path) -> None:
    tool, actuator = _stack(tmp_path)

    receipt = _json_result(
        tool.execute(steps=[{"do": "navigate", "url": "http://127.0.0.1:7777/"}])
    )

    assert receipt["status"] == "completed"
    assert receipt["steps_executed"] == 1
    assert [call["verb"] for call in actuator.calls] == ["navigate"]
    assert receipt["task_completion"] == "not_evaluated"


def test_mf1_short_wire_encodes_replace_as_set_text_not_mode_field(tmp_path: Path) -> None:
    raw = json.loads(json.dumps(FIXTURES["base"]))
    raw["dom"]["nodes"].append(
        {
            "physical_id": "n-project-code",
            "parent_id": "n-root",
            "frame_token": None,
            "kind": "input",
            "attributes": {
                "role": "textbox",
                "name": "Project code",
                "tag": "input",
            },
            "state": {"exists": True, "enabled": True, "visible": True, "editable": True},
        }
    )
    tool, actuator = _stack(tmp_path, raw=raw)

    receipt = _json_result(
        tool.execute(
            steps=[
                {
                    "do": "set_text",
                    "target": {"kind": "input", "name": "Project code"},
                    "text": "ZX-41",
                }
            ]
        )
    )

    assert receipt["status"] == "completed"
    assert actuator.calls[0]["verb"] == "fill"
    assert actuator.calls[0]["args"] == {"text": "ZX-41", "mode": "replace"}


def test_mf1_wait_uses_runtime_poll_interval_default(tmp_path: Path) -> None:
    tool, _ = _stack(tmp_path)

    receipt = _json_result(
        tool.execute(
            steps=[
                {
                    "wait": {
                        "target": {"kind": "button", "name": "Submit"},
                        "enabled": True,
                    },
                    "within_ms": 100,
                }
            ]
        )
    )

    assert receipt["status"] == "completed"
    assert receipt["steps_executed"] == 1


def test_mf1_short_wire_is_closed_and_carries_no_program_strategy_fields() -> None:
    params = BrowserSemanticOperationTool.parameters
    assert params["required"] == ["steps"]
    assert params["additionalProperties"] is False
    wire = json.dumps(params, ensure_ascii=False, sort_keys=True)
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


def test_mf1_declared_navigation_may_continue_to_fresh_exact_target(tmp_path: Path) -> None:
    tool, actuator = _stack(tmp_path)

    receipt = _json_result(
        tool.execute(
            steps=[
                {"do": "navigate", "url": "http://127.0.0.1:7777/"},
                {"do": "click", "target": {"kind": "button", "name": "Submit"}},
            ]
        )
    )

    assert receipt["status"] == "completed"
    assert [call["verb"] for call in actuator.calls] == ["navigate", "click"]


def test_mf1_undeclared_structural_transition_halts_before_later_step(tmp_path: Path) -> None:
    tool, actuator = _stack(
        tmp_path,
        boundary_events=({"kind": "document_transition", "declared": False},),
    )

    receipt = _json_result(
        tool.execute(
            steps=[
                {"do": "click", "target": {"kind": "button", "name": "Submit"}},
                {"do": "click", "target": {"kind": "button", "name": "Submit"}},
            ]
        )
    )

    assert receipt["status"] == "halted"
    assert receipt["halt_reason"] == "undeclared_structural_transition"
    assert len(actuator.calls) == 1
    assert receipt["automatic_retry"] is False


def test_mf1_compact_success_projection_does_not_embed_full_action_receipt(tmp_path: Path) -> None:
    tool, _ = _stack(tmp_path)

    receipt = _json_result(
        tool.execute(steps=[{"do": "click", "target": {"kind": "button", "name": "Submit"}}])
    )

    assert receipt["status"] == "completed"
    assert receipt["receipt_ref"].startswith("browser-operation-receipt://")
    assert receipt["diff_ref"]
    assert "clauses" not in receipt
    assert "action_receipt" not in json.dumps(receipt, sort_keys=True)


def test_mf1_ambiguous_exact_target_halts_without_dispatch_or_best_match(tmp_path: Path) -> None:
    raw = json.loads(json.dumps(FIXTURES["base"]))
    source = next(n for n in raw["dom"]["nodes"] if n.get("attributes", {}).get("name") == "Submit")
    clone = json.loads(json.dumps(source))
    clone["physical_id"] = "second-submit"
    raw["dom"]["nodes"].append(clone)
    tool, actuator = _stack(tmp_path, raw=raw)

    receipt = _json_result(
        tool.execute(steps=[{"do": "click", "target": {"kind": "button", "name": "Submit"}}])
    )

    assert receipt["status"] == "halted"
    assert receipt["halt_reason"] == "ambiguous_target"
    assert receipt["match_count"] > 1
    assert actuator.calls == []


def test_mf1_clause_exhaustion_never_claims_task_completion(tmp_path: Path) -> None:
    tool, _ = _stack(tmp_path)

    receipt = _json_result(
        tool.execute(steps=[{"do": "click", "target": {"kind": "button", "name": "Submit"}}])
    )

    assert receipt["status"] == "completed"
    assert receipt["task_completion"] == "not_evaluated"


def test_mf1_zero_exact_target_halts_without_dispatch(tmp_path: Path) -> None:
    tool, actuator = _stack(tmp_path)

    receipt = _json_result(
        tool.execute(steps=[{"do": "click", "target": {"kind": "button", "name": "Missing"}}])
    )

    assert receipt["status"] == "halted"
    assert receipt["halt_reason"] == "target_not_found"
    assert receipt["match_count"] == 0
    assert actuator.calls == []


def test_mf1_unsatisfied_wait_halts_instead_of_inventing_false_success(tmp_path: Path) -> None:
    raw = json.loads(json.dumps(FIXTURES["base"]))
    submit = next(n for n in raw["dom"]["nodes"] if n.get("attributes", {}).get("name") == "Submit")
    submit["state"]["enabled"] = False
    tool, actuator = _stack(tmp_path, raw=raw)

    receipt = _json_result(
        tool.execute(
            steps=[
                {
                    "wait": {"target": {"kind": "button", "name": "Submit"}, "enabled": True},
                    "within_ms": 1,
                },
                {"do": "click", "target": {"kind": "button", "name": "Submit"}},
            ]
        )
    )

    assert receipt["status"] == "halted"
    assert receipt["halt_reason"] in {
        "predicate_result:unsatisfied",
        "predicate_result:indeterminate",
    }
    assert actuator.calls == []


def test_mf1_existing_stale_and_single_dispatch_guards_remain_backend_authority() -> None:
    # MF must compile into the already-qualified backend rather than replacing these guards.
    source = (ROOT / "tests/unit/test_smc_browser_action_v01.py").read_text()
    version_source = (ROOT / "tests/unit/test_smc_browser_version_pressure_v01.py").read_text()
    assert "version_precondition" in source
    assert "duplicate_action_id" in source
    assert "assess_version_precondition" in version_source
