"""Tool-layer machine authorship of ``args_normalization`` (subject_v01 finding).

Contract under test (measured run run_20260917T231757Z, 30/30 navigate rejections):

1. The model-facing schema of ``browser_action`` declares exactly 13 fields with
   ``additionalProperties: false``; ``args_normalization`` is machine-authored and
   must NOT be model-supplied (``llm_loop.browser.action._valid_args_normalization``
   docstring: "Machine-authored receipt field; never part of the model-owned surface").
2. Therefore the TOOL layer authors the passthrough fact
   ``{"applied": False, "rule": None}`` for schema-shaped actions — mirroring
   ``browser_semantic_execute.compile_request`` — before handing the action to the
   frozen 14-field adapter contract.
3. A schema-shaped (13-field) action must no longer be rejected with
   ``semantic_action_fields_mismatch``; it must proceed to normal domain validation
   and the receipt must record the machine-authored passthrough fact.
4. A hand-authored (schema-violating) ``args_normalization`` value is passed through
   unchanged; the adapter keeps rejecting it fail-closed with
   ``args_normalization_mismatch``. The tool never silently strips or rewrites it.
"""

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
from llm_loop.tools.builtin.browser_action import BrowserActionTool
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)

_URL = "http://127.0.0.1/example"
_PASSTHROUGH = {"applied": False, "rule": None}


class _CaptureBackend:
    def __init__(self, capture: dict[str, Any]) -> None:
        self.capture_value = json.loads(json.dumps(capture))
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        return json.loads(json.dumps(self.capture_value))


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


def _stack(tmp_path: Path):
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    backend = _CaptureBackend(FIXTURES["base"])
    actuator = _Actuator()
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=BrowserActionReceiptStore(tmp_path / "actions"),
        capture_backend=backend,
        actuator=actuator,
    )
    browser_action_tool = BrowserActionTool(
        adapter=action, session_id_getter=lambda: "s1"
    )
    semantic_tool = BrowserSemanticExecuteTool(
        perception=perception, action_adapter=action, session_id_getter=lambda: "s1"
    )
    return perception, backend, actuator, action, browser_action_tool, semantic_tool


def _page_ref(perception: BrowserPerceptionAdapter) -> str:
    first = perception.snapshot("s1", FIXTURES["base"])
    return str(first["resource_ref"])


def _model_shaped(action: dict[str, Any]) -> dict[str, Any]:
    """Drop the machine field: exactly what the advertised 13-field schema allows."""
    return {key: value for key, value in action.items() if key != "args_normalization"}


def test_schema_shaped_click_gets_machine_authorship_and_dispatches(tmp_path: Path) -> None:
    perception, _, actuator, _, browser_action_tool, semantic_tool = _stack(tmp_path)
    first = perception.snapshot("s1", FIXTURES["base"])
    target = next(
        obj
        for obj in first["objects"]
        if obj.get("attributes", {}).get("name") == "Submit"
    )
    compiled = semantic_tool.compile_request(
        "s1",
        {"verb": "click", "target_ref": target["grounding_ref"], "args": {"click": {}}},
    )
    result = browser_action_tool.execute(**_model_shaped(compiled))
    receipt = json.loads(result.content)
    assert receipt["status"] == "ok", receipt
    assert receipt["args_normalization"] == _PASSTHROUGH
    assert actuator.calls and actuator.calls[0]["args"] == {}


def test_schema_shaped_navigate_no_longer_fields_mismatch(tmp_path: Path) -> None:
    # The exact shape that failed 30/30 in run_20260917T231757Z: a navigate
    # SemanticAction carrying the 13 schema-declared fields and nothing else.
    perception, _, _, _, browser_action_tool, semantic_tool = _stack(tmp_path)
    ref = _page_ref(perception)
    compiled = semantic_tool.compile_request(
        "s1", {"verb": "navigate", "target_ref": ref, "args": {"url": _URL}}
    )
    result = browser_action_tool.execute(**_model_shaped(compiled))
    receipt = json.loads(result.content)
    assert receipt["status"] == "ok", receipt
    assert receipt["args_normalization"] == _PASSTHROUGH
    assert receipt["retry"]["reason"] != "semantic_action_fields_mismatch"


def test_hand_authored_normalization_still_fail_closed(tmp_path: Path) -> None:
    perception, _, actuator, _, browser_action_tool, semantic_tool = _stack(tmp_path)
    ref = _page_ref(perception)
    compiled = semantic_tool.compile_request(
        "s1", {"verb": "navigate", "target_ref": ref, "args": {"url": _URL}}
    )
    payload = _model_shaped(compiled)
    payload["args_normalization"] = "not-a-dict"
    result = browser_action_tool.execute(**payload)
    receipt = json.loads(result.content)
    assert receipt["status"] == "rejected"
    assert receipt["retry"]["reason"] == "args_normalization_mismatch"
    assert not actuator.calls
