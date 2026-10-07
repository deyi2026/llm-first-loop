"""FR-2 post-dispatch settle wait (DESIGN-20261007-browser-semantic-guard), M4.

Unit coverage of the adapter-side integration only; the page-side predicates
themselves are exercised by the real-browser E2E suite
(tests/integration/test_browser_dispatch_settle_e2e.py), not faked here —
protocol-level assumptions are only proven against a real CDP round trip.
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
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)

_SETTLED_BASELINE = {
    "schema": "smc.browser_wait_verdict.v0.1",
    "mode": "raf_baseline",
    "verdict": "settled",
    "settled": True,
    "settled_by": "raf",
    "elapsed_ms": 33,
    "cap_ms": 50,
}
_SETTLED_COMBOBOX = {
    "schema": "smc.browser_wait_verdict.v0.1",
    "mode": "combobox_options",
    "verdict": "settled",
    "settled": True,
    "settled_by": "options",
    "visible_options": 2,
    "elapsed_ms": 120,
    "cap_ms": 200,
}


def _by_name(result: dict[str, Any], name: str) -> dict[str, Any]:
    return next(obj for obj in result["objects"] if obj.get("attributes", {}).get("name") == name)


class _CaptureBackend:
    def __init__(self, captures: list[dict[str, Any]]) -> None:
        self.captures = [json.loads(json.dumps(item)) for item in captures]
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        return json.loads(json.dumps(self.captures[0]))


class _SettleActuator:
    def __init__(self, settle_verdict: dict[str, Any] | Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.settle_calls: list[dict[str, Any]] = []
        self.settle_verdict = settle_verdict or _SETTLED_BASELINE

    def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
        self.calls.append(kwargs)
        return BrowserDispatchResult(
            acknowledged=True,
            boundary_events=(),
            completeness_reasons=(),
        )

    def settle(self, *, physical_target: str | None, mode: str) -> dict[str, Any]:
        self.settle_calls.append({"physical_target": physical_target, "mode": mode})
        if isinstance(self.settle_verdict, Exception):
            raise self.settle_verdict
        verdict = copy.deepcopy(self.settle_verdict)
        verdict["mode"] = mode
        return verdict


class _NoSettleActuator:
    """Mimics pre-FR-2 actuator implementations that never grew a settle()."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
        self.calls.append(kwargs)
        return BrowserDispatchResult(acknowledged=True, boundary_events=(), completeness_reasons=())


def _stack(tmp_path: Path, captures: list[dict[str, Any]], actuator: Any, *, settle_enabled: bool):
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    receipts = BrowserActionReceiptStore(tmp_path / "actions")
    backend = _CaptureBackend(captures)
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=receipts,
        capture_backend=backend,
        actuator=actuator,
        settle_enabled=settle_enabled,
    )
    return perception, receipts, backend, actuator, action


def _click_action(first: dict[str, Any], target_name: str, *, action_id: str = "act-1") -> dict[str, Any]:
    target = _by_name(first, target_name)
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


def _combobox_fixture() -> dict[str, Any]:
    fx = copy.deepcopy(FIXTURES["base"])
    for node in fx["dom"]["nodes"]:
        if node["physical_id"] == "n-submit":
            node["kind"] = "select"  # kind truth for role=combobox after _kind_for
            node["attributes"]["role"] = "combobox"
    return fx


def test_settle_disabled_by_default_is_byte_identical_no_wait_no_calls(tmp_path: Path) -> None:
    perception, receipts, _, actuator, action = _stack(
        tmp_path, [FIXTURES["base"]], _SettleActuator(), settle_enabled=False
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first, "Submit"))
    assert result["status"] == "ok"
    assert "wait" not in result  # NFR-3: off = pre-FR-2 receipt shape exactly
    assert actuator.settle_calls == []
    assert "wait" not in receipts.list_action("s1", "act-1")[-1]


def test_settle_runs_baseline_for_plain_click_and_persists_verdict(tmp_path: Path) -> None:
    perception, receipts, _, actuator, action = _stack(
        tmp_path, [FIXTURES["base"]], _SettleActuator(), settle_enabled=True
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first, "Submit"))
    assert result["status"] == "ok"
    assert len(actuator.settle_calls) == 1
    call = actuator.settle_calls[0]
    assert call["mode"] == "raf_baseline"
    assert call["physical_target"] == actuator.calls[0]["physical_target"]
    assert result["wait"]["schema"] == "smc.browser_wait_verdict.v0.1"
    assert result["wait"]["mode"] == "raf_baseline"
    assert result["wait"]["verdict"] == "settled"
    assert receipts.list_action("s1", "act-1")[-1]["wait"]["verdict"] == "settled"


def test_settle_mode_rules_combobox_click_uses_options_predicate(tmp_path: Path) -> None:
    fx = _combobox_fixture()
    perception, _, _, actuator, action = _stack(
        tmp_path, [fx], _SettleActuator(_SETTLED_COMBOBOX), settle_enabled=True
    )
    first = perception.snapshot("s1", fx)
    result = action.execute("s1", _click_action(first, "Submit"))
    assert result["status"] == "ok"
    assert actuator.settle_calls[0]["mode"] == "combobox_options"
    assert result["wait"]["mode"] == "combobox_options"
    assert result["wait"]["visible_options"] == 2


def test_settle_mode_rules_are_pure_server_side_function() -> None:
    assert BrowserActionAdapter._settle_mode("click", {"kind": "combobox"}) == "combobox_options"
    assert BrowserActionAdapter._settle_mode("click", {"kind": "select"}) == "combobox_options"
    assert (
        BrowserActionAdapter._settle_mode("click", {"kind": "input", "attributes": {"role": "listbox"}})
        == "combobox_options"
    )
    assert BrowserActionAdapter._settle_mode("click", {"kind": "button"}) == "raf_baseline"
    assert BrowserActionAdapter._settle_mode("fill", {"kind": "combobox"}) == "raf_baseline"
    assert BrowserActionAdapter._settle_mode("click", None) == "raf_baseline"
    assert BrowserActionAdapter._settle_mode("click", {"kind": "textbox", "attributes": {"role": "textbox"}}) == "raf_baseline"


def test_settle_timeout_verdict_is_honest_and_does_not_fail_the_receipt(tmp_path: Path) -> None:
    timeout = {
        "schema": "smc.browser_wait_verdict.v0.1",
        "mode": "combobox_options",
        "verdict": "timeout",
        "settled": False,
        "settled_by": "cap",
        "visible_options": 0,
        "elapsed_ms": 200,
        "cap_ms": 200,
    }
    fx = _combobox_fixture()
    perception, _, _, actuator, action = _stack(
        tmp_path, [fx], _SettleActuator(timeout), settle_enabled=True
    )
    first = perception.snapshot("s1", fx)
    result = action.execute("s1", _click_action(first, "Submit"))
    assert result["status"] == "ok"  # timeout is honest, never a failure, never retried
    assert result["wait"]["verdict"] == "timeout"
    assert len(actuator.settle_calls) == 1


def test_settle_channel_exception_degrades_to_unavailable_without_raising(tmp_path: Path) -> None:
    perception, _, _, _, action = _stack(
        tmp_path,
        [FIXTURES["base"]],
        _SettleActuator(RuntimeError("cdp boom")),
        settle_enabled=True,
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first, "Submit"))
    assert result["status"] == "ok"  # settle is an observation enhancement, not a gate
    assert result["wait"]["verdict"] == "unavailable"
    assert result["wait"]["reason"].startswith("settle_error:")


def test_settle_absent_on_actuator_records_unavailable(tmp_path: Path) -> None:
    perception, _, _, _, action = _stack(
        tmp_path, [FIXTURES["base"]], _NoSettleActuator(), settle_enabled=True
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first, "Submit"))
    assert result["status"] == "ok"
    assert result["wait"]["verdict"] == "unavailable"
    assert result["wait"]["reason"] == "actuator_no_settle"


def test_settle_skipped_for_navigate(tmp_path: Path) -> None:
    perception, _, _, actuator, action = _stack(
        tmp_path, [FIXTURES["base"]], _SettleActuator(), settle_enabled=True
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    page = next(scope for scope in first["scope_facts"] if scope["kind"] == "page")
    req = {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": page["scope_ref"],
        "action_id": "nav-1",
        "verb": "navigate",
        "target_id": page["scope_ref"],
        "args": {"url": "https://example.test/b"},
        "args_normalization": {"applied": False, "rule": None},
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": first["snapshot"]["snapshot_id"],
        "version_scope": "resource",
        "version_precondition": "required",
    }
    result = action.execute("s1", req)
    assert result["status"] == "ok"
    assert actuator.settle_calls == []  # resource-level transition: boundary wait owns settling
