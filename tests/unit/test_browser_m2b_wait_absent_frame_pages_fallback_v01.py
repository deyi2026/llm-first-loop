# M2-B browser tests: B7 wait absent / B8 frame / B9 pages / B15 fallback
"""M2-B (DESIGN-20261027 §4.1 批B) browser capability tests.

B7 wait absent + settle_ms / B8 frame_token addressing / B9 read-only pages
listing / B15 fallback addressing for nameless elements.  Every capability
runs the REAL production layers (perception adapter, typed wait tools,
perceive/operate tool surfaces) with a positive and a negative case;
negatives assert the deterministic rejection AND the absence of side
effects (no polling / no dispatch / no binding change) - RULE-AI-35.
"""

from __future__ import annotations

import json
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
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool
from llm_loop.tools.builtin.browser_semantic_operation import (
    BrowserSemanticOperationReceiptStore,
    BrowserSemanticOperationTool,
)
from llm_loop.tools.builtin.browser_wait import _AbsentSettleTracker

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)


class _Backend:
    """Read-only capture backend returning a scripted raw-capture sequence.

    The last item repeats (same contract as the M2-A/_SequenceBackend doubles):
    polling loops must terminate on their own deadline, never on backend
    exhaustion.
    """

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = [deepcopy(item) for item in items]
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        return deepcopy(self.items[min(self.calls - 1, len(self.items) - 1)])


class _FlippingBackend:
    """B7 jitter double: presence flips on EVERY capture (never stable)."""

    def __init__(self, present: dict[str, Any], absent: dict[str, Any]) -> None:
        self.present = deepcopy(present)
        self.absent = deepcopy(absent)
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        return deepcopy(self.present if self.calls % 2 == 1 else self.absent)


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


def _adapter(tmp_path: Path) -> BrowserPerceptionAdapter:
    return BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(tmp_path / "p", retention_seconds=600)
    )


def _perceive_tool(adapter: BrowserPerceptionAdapter, backend: Any) -> BrowserPerceiveTool:
    return BrowserPerceiveTool(
        adapter=adapter,
        backend=backend,
        session_id_getter=lambda: "s1",
    )


def _without_submit_fixture() -> dict[str, Any]:
    raw = deepcopy(FIXTURES["base"])
    raw["dom"]["nodes"] = [
        node for node in raw["dom"]["nodes"] if node.get("physical_id") != "n-submit"
    ]
    raw["ax"]["nodes"] = [
        node for node in raw["ax"]["nodes"] if node.get("physical_id") != "n-submit"
    ]
    return raw


def _seed_snapshot(adapter: BrowserPerceptionAdapter) -> str:
    result = adapter.snapshot("s1", deepcopy(FIXTURES["base"]), projection_limit=50)
    for obj in result["objects"]:
        if (obj.get("attributes") or {}).get("name") == "Submit":
            return str(obj["grounding_ref"])
    raise AssertionError("Submit object missing from seeded snapshot")


# ---------------------------------------------------------------------------
# A. B7 wait absent + settle_ms (DESIGN-20261027 §7.3.4)
# ---------------------------------------------------------------------------


def test_b7_settle_tracker_window_and_reset() -> None:
    tracker = _AbsentSettleTracker(100)
    # First satisfied sample only OPENS the window (0ms confirmed absence).
    assert tracker.step(satisfied=True, now=0.0) is False
    assert tracker.step(satisfied=True, now=0.05) is False  # 50ms < 100ms
    assert tracker.step(satisfied=True, now=0.101) is True  # >=100ms confirmed
    assert tracker.receipt(settled=True, now=99.0)["absent_stable_ms"] >= 100
    tracker2 = _AbsentSettleTracker(100)
    assert tracker2.step(satisfied=True, now=0.0) is False
    assert tracker2.step(satisfied=True, now=0.09) is False
    assert tracker2.step(satisfied=False, now=0.095) is False  # re-appeared
    assert tracker2._since is None  # mid-window re-appearance RESETS the timer
    assert tracker2.receipt(settled=False, now=0.095)["absent_stable_ms"] == 0
    assert tracker2.step(satisfied=True, now=0.2) is False  # fresh window
    assert tracker2.step(satisfied=True, now=0.29) is False  # only 90ms since reset
    assert tracker2.step(satisfied=True, now=0.301) is True


def test_b7_absence_settles_after_stable_window(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    ref = _seed_snapshot(adapter)
    backend = _Backend([deepcopy(FIXTURES["base"]), _without_submit_fixture()])
    tool = _perceive_tool(adapter, backend)
    result = tool.execute(
        action="wait",
        kind="object_absent",
        grounding_ref=ref,
        settle_ms=60,
        within_ms=700,
    )
    payload = json.loads(result.content)
    assert payload["predicate_result"]["state"] == "absent"
    assert payload["predicate_result"]["settle_ms"] == 60
    assert payload["predicate_result"]["absent_stable_ms"] >= 60
    assert payload["observation"]["result"] == "satisfied"
    assert backend.calls >= 2  # window needed at least a second sample


def test_b7_jittering_page_never_settles(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    ref = _seed_snapshot(adapter)
    backend = _FlippingBackend(deepcopy(FIXTURES["base"]), _without_submit_fixture())
    tool = _perceive_tool(adapter, backend)
    result = tool.execute(
        action="wait",
        kind="object_absent",
        grounding_ref=ref,
        settle_ms=80,
        within_ms=300,
    )
    payload = json.loads(result.content)
    # Every absence sample is followed by a re-appearance: the window resets
    # forever, so the receipt must be the explicit failure, not absent.
    assert payload["predicate_result"]["state"] == "present"
    assert payload["predicate_result"]["absent_stable_ms"] < 80
    assert backend.calls >= 2


def test_b7_default_settle_window_gates_first_sample_success(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    ref = _seed_snapshot(adapter)
    # Element absent from the FIRST sample, but with the DEFAULT 300ms window
    # and a 250ms poll cadence inside a 350ms budget the last confirmable
    # absence span is ~250ms: the default window must hold the verdict at
    # "present" (a settle-less exists=false wait would succeed on sample 1).
    backend = _Backend([_without_submit_fixture()])
    tool = _perceive_tool(adapter, backend)
    result = tool.execute(
        action="wait",
        kind="object_absent",
        grounding_ref=ref,
        within_ms=350,
    )
    payload = json.loads(result.content)
    assert payload["predicate_result"]["state"] == "present"
    assert payload["predicate_result"]["settle_ms"] == 300
    assert payload["predicate_result"]["absent_stable_ms"] < 300
    assert backend.calls >= 1


@pytest.mark.parametrize("settle_ms", [10, 20000, True, "300"])
def test_b7_settle_ms_bounds_rejected_before_any_polling(
    tmp_path: Path, settle_ms: Any
) -> None:
    adapter = _adapter(tmp_path)
    ref = _seed_snapshot(adapter)
    backend = _Backend([deepcopy(FIXTURES["base"])])
    tool = _perceive_tool(adapter, backend)
    result = tool.execute(
        action="wait",
        kind="object_absent",
        grounding_ref=ref,
        settle_ms=settle_ms,
        within_ms=500,
    )
    assert result.status.value == "failure"
    assert "settle_ms" in result.content
    assert backend.calls == 0  # rejection happened before polling started


def test_b7_settle_ms_greater_than_timeout_rejected(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    ref = _seed_snapshot(adapter)
    backend = _Backend([_without_submit_fixture()])
    tool = _perceive_tool(adapter, backend)
    result = tool.execute(
        action="wait",
        kind="object_absent",
        grounding_ref=ref,
        settle_ms=400,
        within_ms=200,
    )
    assert "settle_ms" in result.content and "timeout_ms" in result.content
    assert backend.calls == 0


def test_b7_settle_field_rejected_on_plain_object_state_wait(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    ref = _seed_snapshot(adapter)
    backend = _Backend([deepcopy(FIXTURES["base"])])
    tool = _perceive_tool(adapter, backend)
    result = tool.execute(
        action="wait",
        kind="object_state",
        grounding_ref=ref,
        state="exists",
        value=False,
        settle_ms=100,
        within_ms=500,
    )
    assert "fields_mismatch" in result.content  # settle only belongs to object_absent
    assert backend.calls == 0


# ---------------------------------------------------------------------------
# B. B8 iframe addressing via the existing frame_token (DESIGN-20261027 F27)
# ---------------------------------------------------------------------------

_FRAME_TOKEN = "frame:child-1"


def _cross_frame_fixture() -> dict[str, Any]:
    """Main-frame Submit button + a same-named Submit button inside one child
    frame (production token shape ``frame:<frameId>``; main frame stays None)."""
    raw = deepcopy(FIXTURES["base"])
    raw["frames"] = [
        {
            "frame_token": _FRAME_TOKEN,
            "document_token": "frame-doc-c1",
            "parent_frame_token": None,
            "same_origin": True,
            "captured": True,
            "url": "https://example.test/inner",
        }
    ]
    raw["dom"]["nodes"].append(
        {
            "physical_id": "n-frame-submit",
            "parent_id": None,
            "frame_token": _FRAME_TOKEN,
            "kind": "button",
            "attributes": {
                "role": "button",
                "name": "Submit",
                "tag": "button",
                "text": "Submit",
            },
            "state": {"exists": True, "enabled": True, "visible": True},
        }
    )
    raw["ax"]["nodes"].append(
        {
            "ax_id": "ax-frame-submit",
            "physical_id": "n-frame-submit",
            "frame_token": _FRAME_TOKEN,
            "kind": "button",
            "attributes": {"role": "button", "name": "Submit"},
            "state": {"exists": True, "enabled": True, "visible": True},
        }
    )
    return raw


def _operate_stack(tmp_path: Path, raw: dict[str, Any]) -> tuple[Any, Any, Any]:
    adapter = _adapter(tmp_path)
    backend = _Backend([raw])
    actuator = _Actuator()
    action = BrowserActionAdapter(
        perception=adapter,
        receipt_store=BrowserActionReceiptStore(tmp_path / "actions"),
        capture_backend=backend,
        actuator=actuator,
    )
    execute = BrowserSemanticExecuteTool(
        perception=adapter, action_adapter=action, session_id_getter=lambda: "s1"
    )
    operation = BrowserSemanticOperationTool(
        perception=adapter,
        capture_backend=backend,
        semantic_execute=execute,
        receipt_store=BrowserSemanticOperationReceiptStore(tmp_path / "receipts"),
        session_id_getter=lambda: "s1",
    )
    return operation, actuator, adapter


def test_b8_snapshot_surfaces_frame_token_on_scopes_and_objects(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    result = adapter.snapshot("s1", _cross_frame_fixture(), projection_limit=50)
    frame_scopes = [f for f in result["scope_facts"] if f.get("kind") == "frame"]
    assert len(frame_scopes) == 1
    assert frame_scopes[0]["frame_token"] == _FRAME_TOKEN  # scope carries the token
    # Both same-named Submit buttons exist; the frame one carries the child
    # token and the main-frame one stays None (F27 vocabulary).
    submit_tokens = sorted(
        str(obj.get("frame_token"))
        for obj in result["objects"]
        if obj.get("kind") == "button"
        and (obj.get("attributes") or {}).get("name") == "Submit"
    )
    assert submit_tokens == ["None", _FRAME_TOKEN]


def test_b8_main_and_frame_buttons_addressed_separately(tmp_path: Path) -> None:
    raw = _cross_frame_fixture()
    operation, actuator, _ = _operate_stack(tmp_path, raw)
    frame_result = json.loads(
        operation.execute(
            do="click",
            target={"kind": "button", "name": "Submit", "frame_token": _FRAME_TOKEN},
        ).content
    )
    assert frame_result["status"] == "completed"
    assert actuator.calls and actuator.calls[0]["physical_target"] == "dom:n-frame-submit"
    main_result = json.loads(
        operation.execute(
            do="click",
            target={"kind": "button", "name": "Submit", "frame_token": None},
        ).content
    )
    assert main_result["status"] == "completed"
    assert actuator.calls[-1]["physical_target"] == "dom:n-submit"


def test_b8_cross_frame_same_name_without_frame_token_is_ambiguous(tmp_path: Path) -> None:
    raw = _cross_frame_fixture()
    operation, actuator, _ = _operate_stack(tmp_path, raw)
    result = json.loads(
        operation.execute(do="click", target={"kind": "button", "name": "Submit"}).content
    )
    assert result["status"] == "halted"
    assert result["halt_reason"] == "ambiguous_target"
    assert result["match_count"] == 2
    assert actuator.calls == []  # deterministic ambiguity: zero dispatch


def test_b8_frame_token_unknown_token_misses_deterministically(tmp_path: Path) -> None:
    raw = _cross_frame_fixture()
    operation, actuator, _ = _operate_stack(tmp_path, raw)
    result = json.loads(
        operation.execute(
            do="click",
            target={"kind": "button", "name": "Submit", "frame_token": "frame:nope"},
        ).content
    )
    assert result["status"] == "halted"
    assert result["halt_reason"] == "target_not_found"
    assert actuator.calls == []


def test_b8_empty_frame_token_rejected_at_compile(tmp_path: Path) -> None:
    raw = _cross_frame_fixture()
    operation, actuator, _ = _operate_stack(tmp_path, raw)
    tool_result = operation.execute(
        do="click",
        target={"kind": "button", "name": "Submit", "frame_token": "  "},
    )
    assert tool_result.status.value == "failure"
    assert "short_target_frame_token_invalid" in tool_result.content
    assert actuator.calls == []


def test_b8_identity_search_projects_frame_token(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.snapshot("s1", _cross_frame_fixture(), projection_limit=50)
    search = adapter.identity_search("s1", {"kind": "button", "name": "Submit"})
    assert search["total"] == 2
    assert sorted(str(item["frame_token"]) for item in search["objects"]) == [
        "None",
        _FRAME_TOKEN,
    ]

