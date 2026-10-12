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
    def capture(self) -> dict[str, Any]:
        return json.loads(json.dumps(FIXTURES["base"]))


class _Actuator:
    def __init__(self, events_by_verb: dict[str, tuple[dict[str, Any], ...]]) -> None:
        self.events_by_verb = events_by_verb
        self.calls: list[str] = []

    def dispatch(self, *, verb: str, **_kwargs: Any) -> BrowserDispatchResult:
        self.calls.append(verb)
        return BrowserDispatchResult(
            acknowledged=True,
            boundary_events=self.events_by_verb.get(verb, ()),
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )


def _tool(tmp_path: Path, events_by_verb: dict[str, tuple[dict[str, Any], ...]]):
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "p"))
    backend = _Backend()
    actuator = _Actuator(events_by_verb)
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "a"),
        capture_backend=backend,
        actuator=actuator,
    )
    semantic = BrowserSemanticExecuteTool(
        perception=perception,
        action_adapter=action,
        session_id_getter=lambda: "s1",
    )
    tool = BrowserSemanticOperationTool(
        perception=perception,
        capture_backend=backend,
        semantic_execute=semantic,
        receipt_store=BrowserSemanticOperationReceiptStore(tmp_path / "r"),
        session_id_getter=lambda: "s1",
    )
    return tool, actuator


def test_mf4_any_mechanical_boundary_after_non_navigation_halts_before_later_step(
    tmp_path: Path,
) -> None:
    for event in ("new_window", "download_started", "dialog_opened", "new_page"):
        case = tmp_path / event
        tool, actuator = _tool(
            case,
            {"click": ({"event": event, "complete": False},)},
        )
        result = tool.execute(
            steps=[
                {"do": "click", "target": {"kind": "button", "name": "Submit"}},
                {"do": "click", "target": {"kind": "button", "name": "Submit"}},
            ]
        )
        compact = json.loads(result.content)
        assert compact["status"] == "halted"
        assert compact["halt_reason"] == "undeclared_structural_transition"
        assert compact["automatic_retry"] is False
        assert len(actuator.calls) == 1


def test_mf4_declared_navigation_boundary_may_continue_to_next_exact_step(tmp_path: Path) -> None:
    tool, actuator = _tool(
        tmp_path,
        {"navigate": ({"event": "navigation_started", "complete": False},)},
    )
    result = tool.execute(
        steps=[
            {"do": "navigate", "url": "http://127.0.0.1:7777/"},
            {"do": "click", "target": {"kind": "button", "name": "Submit"}},
        ]
    )
    compact = json.loads(result.content)
    assert compact["status"] == "completed"
    assert actuator.calls == ["navigate", "click"]
    assert compact["task_completion"] == "not_evaluated"


def test_mf4_boundary_on_final_non_navigation_step_still_returns_control_to_model(
    tmp_path: Path,
) -> None:
    tool, actuator = _tool(
        tmp_path,
        {"click": ({"event": "new_page", "complete": False},)},
    )
    compact = json.loads(
        tool.execute(
            steps=[{"do": "click", "target": {"kind": "button", "name": "Submit"}}]
        ).content
    )
    assert compact["status"] == "halted"
    assert compact["halt_reason"] == "undeclared_structural_transition"
    assert actuator.calls == ["click"]
