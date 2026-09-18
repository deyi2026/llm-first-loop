"""TDD red: deterministic verb-wrapper args normalization for semantic_execute.

Contract under test (GPT ruling 2026-09-13, FC1 fix):

1. Only the fully unambiguous shape ``{verb: {canonical args...}}`` is mechanically
   unwrapped to the canonical args; the value is carried verbatim, nothing is guessed.
2. Any other shape stays fail-closed: rejected with ``args_contract_mismatch``
   exactly as before (multi-key args, inner keys outside the verb contract,
   non-dict wrapper value, ...).
3. Value-level validation runs *after* normalization and keeps its own reason
   (``navigate_args_invalid``), so unwrap never masks a bad value.
4. Wrapper and canonical shapes share one action_id (same declared intent).
5. Every receipt records the mechanical fact
   ``args_normalization={"applied": bool, "rule": "verb_wrapper_unwrap" | null}``.
6. Malformed ``args_normalization`` is rejected with its own reason
   (``args_normalization_mismatch``) - the field is machine-authored, never model-authored.
7. (2026-09-18 live mount fix) Because the field is never model-authored, a *missing*
   ``args_normalization`` is not a model error: ``execute()`` injects the canonical
   ``{"applied": False, "rule": None}`` default so the model-facing 13-field surface
   stays valid; only a malformed value still rejects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from llm_loop.browser.action import (
    BrowserActionAdapter,
    BrowserActionReceiptStore,
    BrowserDispatchResult,
)
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_semantic_execute import BrowserSemanticExecuteTool

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)

_URL = "http://127.0.0.1/example"
_UNWRAP = {"applied": True, "rule": "verb_wrapper_unwrap"}
_PASSTHROUGH = {"applied": False, "rule": None}


def _by_name(result: dict[str, Any], name: str) -> dict[str, Any]:
    return next(obj for obj in result["objects"] if obj.get("attributes", {}).get("name") == name)


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
    tool = BrowserSemanticExecuteTool(
        perception=perception,
        action_adapter=action,
        session_id_getter=lambda: "s1",
    )
    return perception, backend, actuator, action, tool


def _page_ref(perception: BrowserPerceptionAdapter) -> str:
    first = perception.snapshot("s1", FIXTURES["base"])
    return str(first["resource_ref"])


def _hand_action(args_normalization: Any, *, present: bool = True) -> dict[str, Any]:
    act: dict[str, Any] = {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": "br:page:p1",
        "action_id": "sact-x",
        "verb": "click",
        "target_id": "br:obj:submit",
        "args": {},
        "args_normalization": args_normalization,
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": "docv:1",
        "version_scope": "object",
        "version_precondition": "required",
    }
    if not present:
        act.pop("args_normalization")
    return act


# --- 1. deterministic unwrap: only the unambiguous single-wrapper shape ---


def test_navigate_verb_wrapped_args_unwrap_deterministically(tmp_path: Path) -> None:
    perception, _, _, _, tool = _stack(tmp_path)
    ref = _page_ref(perception)
    compiled = tool.compile_request(
        "s1", {"verb": "navigate", "target_ref": ref, "args": {"navigate": {"url": _URL}}}
    )
    assert compiled["args"] == {"url": _URL}
    assert compiled["args_normalization"] == _UNWRAP


def test_canonical_args_pass_through_without_normalization(tmp_path: Path) -> None:
    perception, _, _, _, tool = _stack(tmp_path)
    ref = _page_ref(perception)
    compiled = tool.compile_request(
        "s1", {"verb": "navigate", "target_ref": ref, "args": {"url": _URL}}
    )
    assert compiled["args"] == {"url": _URL}
    assert compiled["args_normalization"] == _PASSTHROUGH


def test_click_empty_wrapper_unwraps(tmp_path: Path) -> None:
    perception, _, _, _, tool = _stack(tmp_path)
    first = perception.snapshot("s1", FIXTURES["base"])
    target = _by_name(first, "Submit")
    compiled = tool.compile_request(
        "s1", {"verb": "click", "target_ref": target["grounding_ref"], "args": {"click": {}}}
    )
    assert compiled["args"] == {}
    assert compiled["args_normalization"] == _UNWRAP


def test_wrapper_and_canonical_shapes_share_action_id(tmp_path: Path) -> None:
    perception, _, _, _, tool = _stack(tmp_path)
    ref = _page_ref(perception)
    wrapped = tool.compile_request(
        "s1", {"verb": "navigate", "target_ref": ref, "args": {"navigate": {"url": _URL}}}
    )
    canonical = tool.compile_request(
        "s1", {"verb": "navigate", "target_ref": ref, "args": {"url": _URL}}
    )
    assert wrapped["action_id"] == canonical["action_id"]


# --- 2. everything ambiguous stays fail-closed as before ---


@pytest.mark.parametrize(
    ("bad_args", "expect_unwrapped"),
    [
        ({"navigate": _URL}, False),                                 # wrapper value is not a dict: no unwrap
        ({"navigate": {"url": _URL, "wait_until": "load"}}, True),   # unwraps; inner keys then rejected
        ({"navigate": {}}, True),                                    # unwraps; inner missing required key
        ({"navigate": {"url": _URL}, "session": "x"}, False),        # extra top-level args key: no unwrap
        ({"url": _URL, "navigate": {"url": _URL}}, False),           # two keys: no unwrap
    ],
)
def test_ambiguous_wrappers_stay_fail_closed(
    tmp_path: Path, bad_args: dict[str, Any], expect_unwrapped: bool
) -> None:
    perception, _, _, _, tool = _stack(tmp_path)
    ref = _page_ref(perception)
    receipt = tool.execute_request(
        "s1", {"verb": "navigate", "target_ref": ref, "args": bad_args}
    )
    assert receipt["status"] == "rejected"
    assert receipt["retry"]["reason"] == "args_contract_mismatch"
    # The receipt records the mechanical fact: unwrap happened only for the fully
    # unambiguous single-wrapper shape; rejection of the inner args comes after.
    assert receipt["args_normalization"] == (_UNWRAP if expect_unwrapped else _PASSTHROUGH)


def test_value_type_errors_keep_their_own_reason_after_unwrap(tmp_path: Path) -> None:
    # {"navigate": {"url": 123}} unwraps mechanically, then the pre-existing value
    # validation rejects it - unwrap must not mask bad values.
    perception, _, _, _, tool = _stack(tmp_path)
    ref = _page_ref(perception)
    receipt = tool.execute_request(
        "s1", {"verb": "navigate", "target_ref": ref, "args": {"navigate": {"url": 123}}}
    )
    assert receipt["status"] == "rejected"
    assert receipt["retry"]["reason"] == "navigate_args_invalid"
    assert receipt["args_normalization"] == _UNWRAP


# --- 5. receipts record the mechanical fact on every terminal path ---


def test_ok_receipt_records_normalization_and_dispatches_canonical_args(tmp_path: Path) -> None:
    perception, backend, actuator, _, tool = _stack(tmp_path)
    first = perception.snapshot("s1", FIXTURES["base"])
    target = _by_name(first, "Submit")
    result = tool.execute(verb="click", target_ref=target["grounding_ref"], args={"click": {}})
    receipt = json.loads(result.content)
    assert receipt["status"] == "ok"
    assert receipt["args_normalization"] == _UNWRAP
    assert actuator.calls[0]["args"] == {}


# --- 6. machine-authored field is itself validated ---


@pytest.mark.parametrize(
    "bad_field",
    [
        "not-a-dict",
        {"applied": "yes", "rule": "verb_wrapper_unwrap"},
        {"applied": True},
        {"applied": True, "rule": "some_other_rule"},
        {"applied": False, "rule": "verb_wrapper_unwrap"},
        {"applied": True, "rule": "verb_wrapper_unwrap", "note": "extra"},
    ],
)
def test_malformed_normalization_field_is_rejected(tmp_path: Path, bad_field: Any) -> None:
    _, _, _, action, _ = _stack(tmp_path)
    receipt = action.execute("s1", _hand_action(bad_field))
    assert receipt["status"] == "rejected"
    assert receipt["retry"]["reason"] == "args_normalization_mismatch"


def test_missing_normalization_field_gets_machine_default(tmp_path: Path) -> None:
    # _hand_action carries a fabricated ref/version, so dispatch must still be
    # rejected by the version precondition - but never again by the missing
    # machine-authored field itself (semantic_action_fields_mismatch).
    _, _, _, action, _ = _stack(tmp_path)
    receipt = action.execute("s1", _hand_action({"applied": False, "rule": None}, present=False))
    assert receipt["status"] == "rejected"
    assert receipt["retry"]["reason"] != "semantic_action_fields_mismatch"
    assert receipt["args_normalization"] == {"applied": False, "rule": None}
