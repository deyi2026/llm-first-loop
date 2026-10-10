from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from llm_loop.browser.action import (
    BrowserActionAdapter,
    BrowserActionReceiptStore,
    BrowserDispatchResult,
)
from llm_loop.browser.perception import (
    BrowserPerceptionAdapter,
    BrowserPerceptionStore,
    normalize_semantic_name,
)
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.builtin.browser_semantic_operation import (
    BrowserSemanticOperationReceiptStore,
    BrowserSemanticOperationTool,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads((ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text())

ZERO_WIDTH_NAME = "\u200b更多"
SPACED_NAME = "  Delete\u00a0Item\u200b "


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


def _raw_with_zero_width_nodes() -> dict[str, Any]:
    raw = copy.deepcopy(FIXTURES["base"])
    raw["dom"]["nodes"].append(
        {
            "physical_id": "n-more",
            "parent_id": "n-root",
            "frame_token": None,
            "kind": "button",
            "attributes": {"role": "button", "name": ZERO_WIDTH_NAME, "tag": "button"},
            "state": {"exists": True, "visible": True},
        }
    )
    raw["dom"]["nodes"].append(
        {
            "physical_id": "n-space",
            "parent_id": "n-root",
            "frame_token": None,
            "kind": "button",
            "attributes": {"role": "button", "name": SPACED_NAME, "tag": "button"},
            "state": {"exists": True, "visible": True},
        }
    )
    raw["ax"]["nodes"].append(
        {
            "ax_id": "ax-more",
            "physical_id": "n-more",
            "frame_token": None,
            "kind": "button",
            "attributes": {"role": "button", "name": ZERO_WIDTH_NAME},
            "state": {"exists": True},
        }
    )
    raw["ax"]["nodes"].append(
        {
            "ax_id": "ax-space",
            "physical_id": "n-space",
            "frame_token": None,
            "kind": "button",
            "attributes": {"role": "button", "name": SPACED_NAME},
            "state": {"exists": True},
        }
    )
    return raw


def _stack(tmp_path: Path):
    raw = _raw_with_zero_width_nodes()
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    backend = _Backend(raw)
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
        receipt_store=BrowserSemanticOperationReceiptStore(tmp_path / "operation_receipts"),
        session_id_getter=lambda: "s1",
    )
    return operation, actuator


def _receipt(result):
    assert result.status.value == "success"
    return json.loads(result.content)


def _button_with_raw_name(items: list[Any], raw_name: str):
    for obj in items:
        if isinstance(obj, dict) and obj.get("name") == raw_name:
            return obj
    return None


def test_normalize_semantic_name_is_deterministic_and_idempotent() -> None:
    assert normalize_semantic_name(ZERO_WIDTH_NAME) == "更多"
    assert normalize_semantic_name(SPACED_NAME) == "Delete Item"
    assert normalize_semantic_name("a\u200bb\u200cc\u200dd\u00ade\ufefff") == "abcdef"
    assert normalize_semantic_name("a\t\n b") == "a b"
    assert normalize_semantic_name("") == ""
    assert normalize_semantic_name(123) == ""  # type: ignore[arg-type]
    for sample in (ZERO_WIDTH_NAME, SPACED_NAME):
        once = normalize_semantic_name(sample)
        assert normalize_semantic_name(once) == once


def test_miss_receipt_exposes_both_addressing_forms_verbatim(tmp_path: Path) -> None:
    tool, actuator = _stack(tmp_path)
    receipt = _receipt(tool.execute(do="click", target={"kind": "button", "name": "更多"}))
    assert receipt["status"] == "halted"
    assert receipt["halt_reason"] == "target_not_found"
    assert receipt["match_count"] == 0
    assert receipt["automatic_retry"] is False
    candidates = receipt["candidates"]
    assert candidates["count"] > 0
    assert 0 < candidates["returned"] <= candidates["max_projection"] == 20
    zero_width = _button_with_raw_name(candidates["items"], ZERO_WIDTH_NAME)
    assert zero_width is not None
    # Raw name echoed verbatim (zero-width rune intact); derived form strips
    # it and collapses whitespace - both visible to the model in one list.
    assert zero_width["name_normalized"] == "更多"
    spaced = _button_with_raw_name(candidates["items"], SPACED_NAME)
    assert spaced is not None
    assert spaced["name_normalized"] == "Delete Item"
    assert isinstance(zero_width["grounding_ref"], str) and zero_width["grounding_ref"]
    assert actuator.calls == []


def test_name_normalized_addressing_dispatches_unique_match(tmp_path: Path) -> None:
    tool, actuator = _stack(tmp_path)
    receipt = _receipt(tool.execute(do="click", target={"kind": "button", "name_normalized": "更多"}))
    assert receipt["status"] == "completed"
    assert receipt["match_count"] == 1
    assert len(actuator.calls) == 1
    assert actuator.calls[0]["physical_target"] == "dom:n-more"
    # Raw-name addressing for the same visible label must still miss: the two
    # forms stay exact and independent, no fuzzy fallback in either direction.
    miss = _receipt(tool.execute(do="click", target={"kind": "button", "name": "更多"}))
    assert miss["status"] == "halted"
    assert len(actuator.calls) == 1


def test_grounding_ref_addressing_dispatches_and_bad_refs_fail_deterministically(
    tmp_path: Path,
) -> None:
    tool, actuator = _stack(tmp_path)
    miss = _receipt(tool.execute(do="click", target={"kind": "button", "name": "更多"}))
    zero_width = _button_with_raw_name(miss["candidates"]["items"], ZERO_WIDTH_NAME)
    assert zero_width is not None
    ref = zero_width["grounding_ref"]

    hit = _receipt(tool.execute(do="click", target={"grounding_ref": ref}))
    assert hit["status"] == "completed"
    assert hit["match_count"] == 1
    assert len(actuator.calls) == 1
    assert actuator.calls[0]["physical_target"] == "dom:n-more"

    bad = _receipt(
        tool.execute(do="click", target={"grounding_ref": "snapshot:S999/object/nope"})
    )
    assert bad["status"] == "halted"
    assert bad["halt_reason"] == "grounding_ref_unavailable"
    assert bad["grounding_availability"]["availability"] == "unavailable"
    assert len(actuator.calls) == 1  # unchanged: no dispatch, no retry


def test_clause_miss_receipt_keeps_blocked_clause_with_candidates(tmp_path: Path) -> None:
    tool, actuator = _stack(tmp_path)
    result = tool.execute(
        clauses=[
            {
                "kind": "mutate",
                "verb": "click",
                "target": {"kind": "object", "identity": {"kind": "button", "name": "更多"}},
                "args": {},
            }
        ]
    )
    receipt = _receipt(result)
    assert receipt["execution_status"] == "halted"
    blocked = receipt["clauses"][0]
    assert blocked["status"] == "blocked"
    assert blocked["exact_match_count"] == 0
    assert blocked["candidates"]["count"] > 0
    assert blocked["identity"] == {"kind": "button", "name": "更多"}
    assert actuator.calls == []


def test_mixing_addressing_forms_is_rejected_deterministically(tmp_path: Path) -> None:
    tool, _ = _stack(tmp_path)
    result = tool.execute(
        do="click",
        target={"kind": "button", "name": "更多", "name_normalized": "更多"},
    )
    assert result.status.value == "failure"
    assert "short_target_name_addressing_conflict" in result.content

    clause_result = tool.execute(
        clauses=[
            {
                "kind": "mutate",
                "verb": "click",
                "target": {
                    "kind": "object",
                    "identity": {"kind": "button", "name": "更多", "name_normalized": "更多"},
                },
                "args": {},
            }
        ]
    )
    assert clause_result.status.value == "failure"
    assert "identity_name_addressing_conflict" in clause_result.content

    mixed_ref = tool.execute(
        do="click",
        target={"kind": "button", "name": "更多", "grounding_ref": "snapshot:S1/object/x"},
    )
    assert mixed_ref.status.value == "failure"
    assert "short_target_fields_mismatch" in mixed_ref.content
