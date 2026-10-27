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


# ---------------------------------------------------------------------------
# C. B9 read-only pages listing (DESIGN-20261027 §4.1/B9)
# ---------------------------------------------------------------------------


class _PageController:
    """B9 double: read-only /json/list-shaped listing + binding identity."""

    def __init__(self, pages: list[dict[str, str]], binding: dict[str, str] | None):
        from llm_loop.browser.errors import PageRecord

        self.records = [
            PageRecord(
                page_id=str(p["page_id"]),
                url=str(p["url"]),
                title=str(p["title"]),
                websocket_url=str(p["websocket_url"]),
            )
            for p in pages
        ]
        self._binding = binding
        self.rebind_calls: list[str] = []
        self.list_calls = 0

    def list_pages(self) -> list[Any]:
        self.list_calls += 1
        return list(self.records)

    def current_binding(self) -> dict[str, str] | None:
        return dict(self._binding) if self._binding else None

    def rebind(self, target_id: str) -> dict[str, str]:
        self.rebind_calls.append(str(target_id))
        return {"page_id": str(target_id)}


_PAGES = [
    {
        "page_id": "target-a",
        "url": "http://127.0.0.1/a",
        "title": "Page A",
        "websocket_url": "ws://127.0.0.1:9222/devtools/page/target-a",
    },
    {
        "page_id": "target-b",
        "url": "http://127.0.0.1/b",
        "title": "Page B",
        "websocket_url": "ws://127.0.0.1:9222/devtools/page/target-b",
    },
    {
        "page_id": "target-c",
        "url": "http://127.0.0.1/c",
        "title": "Page C",
        "websocket_url": "ws://127.0.0.1:9222/devtools/page/target-c",
    },
]


def _b9_tool(
    tmp_path: Path, controller: _PageController | None
) -> tuple[BrowserPerceiveTool, Any]:
    adapter = _adapter(tmp_path)
    backend = _Backend([deepcopy(FIXTURES["base"])])
    tool = BrowserPerceiveTool(
        adapter=adapter,
        backend=backend,
        session_id_getter=lambda: "s1",
        page_controller=controller,
    )
    return tool, adapter


def test_b9_pages_lists_all_pages_in_healthy_state_without_rebinding(
    tmp_path: Path,
) -> None:
    controller = _PageController(_PAGES, binding=None)
    controller._binding = {
        "browser_ws_uuid": "uuid-1",
        "target_id": "target-b",
        "target_ws_url": "ws://127.0.0.1:9222/devtools/page/target-b",
    }
    tool, adapter = _b9_tool(tmp_path, controller)
    seeded = adapter.snapshot("s1", deepcopy(FIXTURES["base"]), projection_limit=5)
    world_before = str(seeded["snapshot"]["snapshot_id"])
    binding_before = controller.current_binding()

    result = tool.execute(action="pages")
    payload = json.loads(result.content)

    assert payload["action"] == "pages" and payload["read_only"] is True
    assert payload["page_count"] == 3
    bound_flags = {page["page_id"]: page["bound"] for page in payload["pages"]}
    assert bound_flags == {"target-a": False, "target-b": True, "target-c": False}
    assert payload["binding_page_id"] == "target-b"
    # 只读合同（不是口头保证）：调用前后绑定与 world_version 不变。
    assert payload["world_version"] == world_before
    assert controller.current_binding() == binding_before
    assert controller.rebind_calls == []
    assert adapter.latest_world_version("s1") == world_before
    assert backend_never_touched(tool) is True


def backend_never_touched(tool: BrowserPerceiveTool) -> bool:
    # The pages action must not drive the capture backend at all.
    backend = getattr(tool, "_backend", None)
    return getattr(backend, "calls", -1) in (0, -1)


def test_b9_pages_rejects_target_id_without_any_rebind(tmp_path: Path) -> None:
    controller = _PageController(_PAGES, binding=None)
    tool, _ = _b9_tool(tmp_path, controller)
    result = tool.execute(action="pages", target_id="target-c")
    assert result.status.value == "failure"
    assert "fields_mismatch" in result.content
    assert controller.rebind_calls == []  # the read path never rebinds
    assert controller.list_calls == 0


def test_b9_pages_rejects_unknown_fields(tmp_path: Path) -> None:
    controller = _PageController(_PAGES, binding=None)
    tool, _ = _b9_tool(tmp_path, controller)
    result = tool.execute(action="pages", page_count=3)
    assert result.status.value == "failure"
    assert "fields_mismatch" in result.content
    assert controller.list_calls == 0


def test_b9_pages_without_controller_fails_deterministically(tmp_path: Path) -> None:
    tool, _ = _b9_tool(tmp_path, None)
    result = tool.execute(action="pages")
    assert result.status.value == "failure"
    assert "page controller" in result.content


def test_b9_latest_world_version_is_none_before_any_snapshot(tmp_path: Path) -> None:
    controller = _PageController(_PAGES, binding=None)
    tool, adapter = _b9_tool(tmp_path, controller)
    assert adapter.latest_world_version("s1") is None
    result = tool.execute(action="pages")
    payload = json.loads(result.content)
    assert payload["world_version"] is None  # honest: no snapshot yet


# ---------------------------------------------------------------------------
# D. B15 fallback addressing for nameless (icon-only) elements (§7.3.3)
# ---------------------------------------------------------------------------


def _nameless_node(physical: str, extra_attributes: dict[str, Any]) -> dict[str, Any]:
    return {
        "physical_id": physical,
        "parent_id": None,
        "frame_token": None,
        "kind": "button",
        "attributes": {"role": "button", "tag": "button", **extra_attributes},
        "state": {"exists": True, "enabled": True, "visible": True},
    }


def _icon_fixture(*extra: dict[str, Any]) -> dict[str, Any]:
    """base + one title-keyed icon button + one attribute-less icon button."""
    raw = deepcopy(FIXTURES["base"])
    raw["dom"]["nodes"].append(_nameless_node("n-icon-close", {"title": "Close panel"}))
    raw["ax"]["nodes"].append(
        {
            "ax_id": "ax-icon-close",
            "physical_id": "n-icon-close",
            "frame_token": None,
            "kind": "button",
            "attributes": {"role": "button"},  # AX sees no name either
            "state": {"exists": True, "enabled": True, "visible": True},
        }
    )
    raw["dom"]["nodes"].append(_nameless_node("n-icon-bare", {}))
    raw["ax"]["nodes"].append(
        {
            "ax_id": "ax-icon-bare",
            "physical_id": "n-icon-bare",
            "frame_token": None,
            "kind": "button",
            "attributes": {"role": "button"},
            "state": {"exists": True, "enabled": True, "visible": True},
        }
    )
    for node in extra:
        raw["dom"]["nodes"].append(node)
    return raw


def _fallback_facts(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        (obj.get("attributes") or {}).get(
            "fallback_key", (obj.get("attributes") or {}).get("name")
        ): obj.get("attributes") or {}
        for obj in result["objects"]
        if obj.get("kind") == "button"
    }


def test_b15_snapshot_derives_deterministic_fallback_keys(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    result = adapter.snapshot("s1", _icon_fixture(), projection_limit=50)
    snapshot_id = str(result["snapshot"]["snapshot_id"])
    facts = _fallback_facts(result)
    # Named buttons keep the {kind,name} address only - no fallback keys.
    assert "fallback_key" not in facts["Submit"] and "fallback_key" not in facts["Cancel"]
    # title beats ordinal for the titled icon button; the bare icon button
    # falls to the region ordinal counting ALL buttons in traversal order
    # (Submit=1, Cancel=2, icon-close=3, icon-bare=4).
    assert facts["Close panel"]["fallback_key"] == "Close panel"
    assert facts["Close panel"]["fallback_stable_within"] == snapshot_id
    assert facts["button#4"]["fallback_key"] == "button#4"
    assert facts["button#4"]["fallback_stable_within"] == snapshot_id


def test_b15_icon_button_hit_via_fallback_key(tmp_path: Path) -> None:
    raw = _icon_fixture()
    adapter = _adapter(tmp_path)
    seeded = adapter.snapshot("s1", deepcopy(raw), projection_limit=50)
    world = str(seeded["snapshot"]["snapshot_id"])
    backend = _Backend([deepcopy(raw)])
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
    result = json.loads(
        operation.execute(
            do="click",
            target={
                "kind": "button",
                "fallback": "Close panel",
                "fallback_world_version": world,
            },
        ).content
    )
    assert result["status"] == "completed"
    assert actuator.calls and actuator.calls[0]["physical_target"] == "dom:n-icon-close"


def test_b15_cross_world_version_fallback_is_explicitly_stale(tmp_path: Path) -> None:
    raw = _icon_fixture()
    adapter = _adapter(tmp_path)
    seeded = adapter.snapshot("s1", deepcopy(raw), projection_limit=50)
    world = str(seeded["snapshot"]["snapshot_id"])
    # The live world CHANGED after the model's snapshot: the addressed icon
    # button itself is GONE (the classic shifted/removed-ordinal case).
    shifted = deepcopy(raw)
    shifted["dom"]["nodes"] = [
        node
        for node in shifted["dom"]["nodes"]
        if node.get("physical_id") != "n-icon-close"
    ]
    shifted["ax"]["nodes"] = [
        node
        for node in shifted["ax"]["nodes"]
        if node.get("physical_id") != "n-icon-close"
    ]
    backend = _Backend([deepcopy(shifted)])
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
    result = json.loads(
        operation.execute(
            do="click",
            target={
                "kind": "button",
                "fallback": "Close panel",
                "fallback_world_version": world,
            },
        ).content
    )
    # The fallback resolved inside its own world_version but the dispatch-
    # time version guard refused the drifted world (target absent): the
    # receipt must say stale + guidance explicitly - never a silent hit.
    assert result["status"] == "halted"
    assert actuator.calls == []
    annotation = result.get("fallback_addressing")
    assert annotation is not None
    assert annotation["status"] == "stale"
    assert annotation["stable_within"] == world
    assert "snapshot" in annotation["guidance"]


def test_b15_unknown_world_version_rejected_with_guidance(tmp_path: Path) -> None:
    raw = _icon_fixture()
    operation, actuator, _ = _operate_stack(tmp_path, raw)
    result = json.loads(
        operation.execute(
            do="click",
            target={
                "kind": "button",
                "fallback": "Close panel",
                "fallback_world_version": "bsnap-99-doesnotexist",
            },
        ).content
    )
    assert result["status"] == "halted"
    assert result["halt_reason"] == "fallback_world_version_stale"
    assert result["fallback_addressing"]["status"] == "stale"
    assert actuator.calls == []


def test_b15_duplicate_fallback_keys_are_ambiguous(tmp_path: Path) -> None:
    raw = _icon_fixture(_nameless_node("n-icon-close-2", {"title": "Close panel"}))
    raw["ax"]["nodes"].append(
        {
            "ax_id": "ax-icon-close-2",
            "physical_id": "n-icon-close-2",
            "frame_token": None,
            "kind": "button",
            "attributes": {"role": "button"},
            "state": {"exists": True, "enabled": True, "visible": True},
        }
    )
    adapter = _adapter(tmp_path)
    seeded = adapter.snapshot("s1", deepcopy(raw), projection_limit=50)
    world = str(seeded["snapshot"]["snapshot_id"])
    operation, actuator, _ = _operate_stack(tmp_path, deepcopy(raw))
    result = json.loads(
        operation.execute(
            do="click",
            target={
                "kind": "button",
                "fallback": "Close panel",
                "fallback_world_version": world,
            },
        ).content
    )
    assert result["status"] == "halted"
    assert result["halt_reason"] == "fallback_ambiguous"
    assert actuator.calls == []


@pytest.mark.parametrize(
    ("target", "expected_error"),
    [
        (
            {"kind": "button", "fallback": "Close panel"},
            "short_target_fallback_pair_incomplete",
        ),
        (
            {
                "kind": "button",
                "fallback": "Close panel",
                "fallback_world_version": "bsnap-1-x",
                "name": "Submit",
            },
            "short_target_fallback_name_conflict",
        ),
        (
            {"kind": "button", "fallback": "  ", "fallback_world_version": "bsnap-1-x"},
            "short_target_fallback_missing",
        ),
    ],
)
def test_b15_fallback_form_violations_rejected_at_compile(
    tmp_path: Path, target: dict[str, Any], expected_error: str
) -> None:
    raw = _icon_fixture()
    operation, actuator, _ = _operate_stack(tmp_path, raw)
    tool_result = operation.execute(do="click", target=target)
    assert tool_result.status.value == "failure"
    assert expected_error in tool_result.content
    assert actuator.calls == []

