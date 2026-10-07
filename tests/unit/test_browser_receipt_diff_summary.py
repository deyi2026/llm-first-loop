"""FR-5b inline diff summary on terminal action receipts (DESIGN-20261007-browser-semantic-guard), M7.

Covers: NFR-3 default-off byte identity, receipt-level integration on a real
perception diff (field-name granularity, no values inlined), the summary
function's per-class cap/truncation/unknown semantics, and the consumer-side
compact path where an inline summary must render the same delta counts the
hydrate round trip would produce — plus honest fallback for pre-FR-5b
receipts and non-comparable summaries.
"""

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
    diff_summary_for_receipt,
)
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.builtin.browser_semantic_operation import (
    BrowserSemanticOperationReceiptStore,
    BrowserSemanticOperationTool,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)


class _SequenceCaptureBackend:
    """Serves capture() calls from an ordered list; repeats the last one."""

    def __init__(self, captures: list[dict[str, Any]]) -> None:
        self.captures = [json.loads(json.dumps(item)) for item in captures]
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        index = min(self.calls, len(self.captures) - 1)
        self.calls += 1
        return json.loads(json.dumps(self.captures[index]))


class _AckActuator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
        self.calls.append(kwargs)
        return BrowserDispatchResult(acknowledged=True, boundary_events=(), completeness_reasons=())


def _mutated_before() -> dict[str, Any]:
    """before capture: n-cancel missing, n-submit renamed (after = pristine base)."""
    fx = copy.deepcopy(FIXTURES["base"])
    fx["dom"]["nodes"] = [
        node for node in fx["dom"]["nodes"] if node.get("physical_id") != "n-cancel"
    ]
    if isinstance(fx.get("ax"), dict) and isinstance(fx["ax"].get("nodes"), list):
        fx["ax"]["nodes"] = [
            node for node in fx["ax"]["nodes"] if node.get("physical_id") != "n-cancel"
        ]
    # name changes must land on both DOM and AX layers (merged projection).
    for layer in (fx["dom"]["nodes"], fx.get("ax", {}).get("nodes") or []):
        for node in layer:
            if node.get("physical_id") == "n-submit":
                node["attributes"]["name"] = "Submit Changed"
    return fx


def _stack(
    tmp_path: Path,
    *,
    summary_enabled: bool = False,
    summary_cap: int = 32,
):
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    receipts = BrowserActionReceiptStore(tmp_path / "actions")
    backend = _SequenceCaptureBackend([_mutated_before(), FIXTURES["base"]])
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=receipts,
        capture_backend=backend,
        actuator=_AckActuator(),
        receipt_diff_summary_enabled=summary_enabled,
        receipt_diff_summary_cap=summary_cap,
    )
    return perception, receipts, backend, action


def _click_action(first: dict[str, Any], target_name: str, *, action_id: str = "act-1") -> dict[str, Any]:
    target = next(
        obj
        for obj in first["objects"]
        if obj.get("attributes", {}).get("name") == target_name
    )
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


def _operation_tool(
    tmp_path: Path, perception: BrowserPerceptionAdapter, action: BrowserActionAdapter
) -> BrowserSemanticOperationTool:
    return BrowserSemanticOperationTool(
        perception=perception,
        capture_backend=_SequenceCaptureBackend([FIXTURES["base"]]),
        semantic_execute=BrowserSemanticExecuteTool(
            perception=perception,
            action_adapter=action,
            session_id_getter=lambda: "s1",
        ),
        receipt_store=BrowserSemanticOperationReceiptStore(tmp_path / "op_receipts"),
        session_id_getter=lambda: "s1",
    )


def _full_receipt(action_receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "execution_status": "clauses_exhausted",
        "clauses": [{"action_receipt": action_receipt}],
    }


# ── NFR-3: default off = pre-FR-5b receipt shape exactly ─────────────────────


def test_disabled_by_default_receipt_has_no_diff_summary(tmp_path: Path) -> None:
    perception, receipts, _, action = _stack(tmp_path, summary_enabled=False)
    first = perception.snapshot("s1", _mutated_before())
    result = action.execute("s1", _click_action(first, "Submit Changed"))
    assert result["status"] == "ok"
    assert "diff_summary" not in result["observed_effects"]
    persisted = receipts.list_action("s1", "act-1")[-1]
    assert "diff_summary" not in persisted["observed_effects"]


# ── Receipt integration on a real perception diff ────────────────────────────


def test_enabled_inline_summary_field_names_only_no_values(tmp_path: Path) -> None:
    perception, receipts, _, action = _stack(tmp_path, summary_enabled=True)
    first = perception.snapshot("s1", _mutated_before())
    result = action.execute("s1", _click_action(first, "Submit Changed"))
    assert result["status"] == "ok"
    observed = result["observed_effects"]
    summary = observed["diff_summary"]
    assert summary["schema"] == "smc.browser_diff_summary.v0.1"
    assert summary["comparable"] is True
    assert summary["complete"] is True
    assert summary["cap"] == 32
    # Renamed submit (attributes.name) plus the root's relations shift from the
    # re-appearing cancel node; both carry field names only.
    assert summary["changed"]["total"] == 2
    changed_entries = summary["changed"]["items"]
    assert all(set(entry) == {"id", "fields"} for entry in changed_entries)
    assert any(entry["fields"] == ["attributes.name"] for entry in changed_entries)
    assert any("relations" in entry["fields"] for entry in changed_entries)
    # Re-appearing cancel -> created.
    assert summary["created"]["total"] == 1
    assert summary["created"]["truncated"] is False
    assert summary["removed"]["total"] == 0
    assert summary["removed"]["items"] == []
    # No values anywhere in the summary — ids and field names only.
    serialized = json.dumps(summary, ensure_ascii=False)
    for value in ("Submit", "Cancel", "Example"):
        assert value not in serialized
    # Persisted terminal receipt carries the same inline summary.
    persisted = receipts.list_action("s1", "act-1")[-1]
    assert persisted["observed_effects"]["diff_summary"] == summary


def test_enabled_cap_calibrates_inline_entries(tmp_path: Path) -> None:
    perception, _, _, action = _stack(tmp_path, summary_enabled=True, summary_cap=1)
    first = perception.snapshot("s1", _mutated_before())
    result = action.execute("s1", _click_action(first, "Submit Changed"))
    summary = result["observed_effects"]["diff_summary"]
    assert summary["cap"] == 1
    assert summary["created"]["returned"] == 1
    assert summary["created"]["truncated"] is False  # exactly one created object
    # Truncation must be honest when totals exceed the cap.
    from llm_loop.browser.perception import diff_summary_for_receipt as _summarize

    synthetic = _summarize(
        {"comparable": True, "created": [f"id-{i}" for i in range(40)]}, cap=1
    )
    assert synthetic["created"]["total"] == 40
    assert synthetic["created"]["returned"] == 1
    assert synthetic["created"]["truncated"] is True
    assert synthetic["created"]["items"] == ["id-0"]


# ── Summary function semantics (synthetic diff documents) ───────────────────


def _synthetic_diff(**overrides: Any) -> dict[str, Any]:
    diff: dict[str, Any] = {
        "comparable": True,
        "scope_relation": "same_document",
        "completeness": {"complete": True, "reasons": []},
        "created": ["a", "b"],
        "removed": ["c"],
        "changed": [{"id": "d", "fields": ["state.visible", "attributes.name"]}],
    }
    diff.update(overrides)
    return diff


def test_summary_function_cap_truncation_per_class() -> None:
    summary = diff_summary_for_receipt(
        _synthetic_diff(
            created=[f"c-{i}" for i in range(40)],
            removed=[f"r-{i}" for i in range(40)],
            changed=[{"id": f"h-{i}", "fields": ["state.visible"]} for i in range(40)],
        )
    )
    for section_name in ("created", "removed", "changed"):
        section = summary[section_name]
        assert section["total"] == 40
        assert section["returned"] == 32
        assert section["truncated"] is True
        assert len(section["items"]) == 32
    assert summary["changed"]["items"][0] == {"id": "h-0", "fields": ["state.visible"]}
    assert summary["cap"] == 32


def test_summary_function_unknown_sections_stay_none() -> None:
    summary = diff_summary_for_receipt(_synthetic_diff(created=None, removed=None))
    assert summary["created"] is None  # unknown, deliberately distinct from total=0
    assert summary["removed"] is None
    assert summary["changed"]["total"] == 1


def test_summary_function_not_comparable_omits_classes() -> None:
    summary = diff_summary_for_receipt(_synthetic_diff(comparable=False))
    assert summary["comparable"] is False
    for key in ("created", "removed", "changed"):
        assert key not in summary


# ── Consumer-side compact projection: closed loop without a hydrate hop ─────


def test_compact_inline_path_renders_same_counts_as_hydrate(tmp_path: Path) -> None:
    perception_off, _, _, action_off = _stack(tmp_path / "off", summary_enabled=False)
    first_off = perception_off.snapshot("s1", _mutated_before())
    receipt_off = action_off.execute("s1", _click_action(first_off, "Submit Changed"))

    perception_on, _, _, action_on = _stack(tmp_path / "on", summary_enabled=True)
    first_on = perception_on.snapshot("s1", _mutated_before())
    receipt_on = action_on.execute("s1", _click_action(first_on, "Submit Changed"))

    tool_off = _operation_tool(tmp_path / "off", perception_off, action_off)
    tool_on = _operation_tool(tmp_path / "on", perception_on, action_on)
    delta_off = tool_off._compact_projection("s1", _full_receipt(receipt_off), "ref-off")["delta"]
    delta_on = tool_on._compact_projection("s1", _full_receipt(receipt_on), "ref-on")["delta"]

    # Hydrate path (pre-FR-5b receipt) and inline path must agree on facts.
    for field in ("comparable", "scope_relation", "complete", "reasons", "counts"):
        assert delta_off[field] == delta_on[field], field
    assert delta_off["counts"] == {
        "created": 1,
        "removed": 0,
        "changed": 2,
    }
    # The inline path additionally exposes the summary itself — no values.
    assert delta_on["diff_summary"] == receipt_on["observed_effects"]["diff_summary"]
    assert "diff_summary" not in delta_off


def test_compact_old_receipt_and_non_comparable_summary_fall_back(tmp_path: Path) -> None:
    perception, _, _, action = _stack(tmp_path, summary_enabled=True)
    first = perception.snapshot("s1", _mutated_before())
    receipt = action.execute("s1", _click_action(first, "Submit Changed"))
    tool = _operation_tool(tmp_path, perception, action)

    # Pre-FR-5b receipt (no summary key) → hydrate path, still works.
    legacy = copy.deepcopy(receipt)
    legacy["observed_effects"].pop("diff_summary")
    delta_legacy = tool._compact_projection("s1", _full_receipt(legacy), "ref-legacy")["delta"]
    assert delta_legacy["counts"]["changed"] == 2
    assert "diff_summary" not in delta_legacy

    # Non-comparable summary → fall through to hydrate, honest degradation.
    non_comparable = copy.deepcopy(receipt)
    non_comparable["observed_effects"]["diff_ref"] = "diff://nonexistent/non-comparable"
    non_comparable["observed_effects"]["diff_summary"] = {"comparable": False}
    delta_nc = tool._compact_projection("s1", _full_receipt(non_comparable), "ref-nc")["delta"]
    assert delta_nc["comparable"] is None
    assert any("diff_unavailable" in str(reason) for reason in delta_nc["reasons"])
