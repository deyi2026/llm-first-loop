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

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads((ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text())


class _Backend:
    def __init__(self) -> None:
        self.raw = json.loads(json.dumps(FIXTURES["base"]))

    def capture(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.raw))


class _Actuator:
    def dispatch(self, **_kwargs: Any) -> BrowserDispatchResult:
        return BrowserDispatchResult(
            acknowledged=True,
            boundary_events=(),
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )


def _stack(tmp_path: Path):
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    backend = _Backend()
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
    return operation, operation_store, perceive


def test_mf3_model_gets_compact_projection_while_full_receipt_is_exactly_hydratable(
    tmp_path: Path,
) -> None:
    operation, store, _ = _stack(tmp_path)
    result = operation.execute(
        steps=[{"do": "click", "target": {"kind": "button", "name": "Submit"}}]
    )
    assert result.status.value == "success"
    compact = json.loads(result.content)

    assert compact["status"] == "completed"
    assert compact["task_completion"] == "not_evaluated"
    assert compact["receipt_ref"].startswith("browser-operation-receipt://v0.1/")
    assert compact["diff_ref"].startswith("grounding://browser/v0.1/")
    assert "clauses" not in compact
    assert "action_receipt" not in result.content

    hydrated = store.hydrate("s1", compact["receipt_ref"])
    assert hydrated["availability"] == "available"
    full = hydrated["content"]
    assert full["execution_status"] == "clauses_exhausted"
    assert full["task_completion"] == "not_evaluated"
    assert full["clauses"][0]["action_receipt"]["status"] == "ok"
    assert full["clauses"][0]["action_receipt"]["observed_effects"]["diff_ref"] == compact["diff_ref"]


def test_mf3_browser_perceive_hydrates_operation_receipt_without_new_tool_surface(
    tmp_path: Path,
) -> None:
    operation, _, perceive = _stack(tmp_path)
    compact = json.loads(
        operation.execute(
            steps=[{"do": "click", "target": {"kind": "button", "name": "Submit"}}]
        ).content
    )

    result = perceive.execute(action="hydrate", grounding_ref=compact["receipt_ref"])
    assert result.status.value == "success"
    hydrated = json.loads(result.content)
    assert hydrated["availability"] == "available"
    assert hydrated["content"]["schema"] == "smc.bounded_semantic_operation_receipt.v0.1"


def test_mf3_receipt_ref_is_session_fenced(tmp_path: Path) -> None:
    operation, store, _ = _stack(tmp_path)
    compact = json.loads(
        operation.execute(
            steps=[{"do": "click", "target": {"kind": "button", "name": "Submit"}}]
        ).content
    )
    cross_session = store.hydrate("other-session", compact["receipt_ref"])
    assert cross_session["availability"] in {"unavailable", "unauthorized"}
    assert "content" not in cross_session


def test_mf3_compact_projection_is_materially_smaller_than_full_receipt(tmp_path: Path) -> None:
    operation, store, _ = _stack(tmp_path)
    result = operation.execute(
        steps=[{"do": "click", "target": {"kind": "button", "name": "Submit"}}]
    )
    compact = json.loads(result.content)
    full = store.hydrate("s1", compact["receipt_ref"])["content"]
    compact_wire = json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    full_wire = json.dumps(full, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert len(compact_wire) < len(full_wire) * 0.5
