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

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)


def _by_name(result: dict[str, Any], name: str) -> dict[str, Any]:
    return next(obj for obj in result["objects"] if obj.get("attributes", {}).get("name") == name)


class _CaptureBackend:
    def __init__(self, captures: list[dict[str, Any]]) -> None:
        self.captures = [json.loads(json.dumps(item)) for item in captures]
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        if not self.captures:
            raise RuntimeError("no capture")
        if len(self.captures) == 1:
            return json.loads(json.dumps(self.captures[0]))
        return json.loads(json.dumps(self.captures.pop(0)))


class _Actuator:
    def __init__(self, result: BrowserDispatchResult | Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = result or BrowserDispatchResult(
            acknowledged=True,
            boundary_events=(),
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )

    def dispatch(self, **kwargs: Any) -> BrowserDispatchResult:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _stack(tmp_path: Path, captures: list[dict[str, Any]], actuator: _Actuator | None = None):
    perception = BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(tmp_path / "perception")
    )
    receipts = BrowserActionReceiptStore(tmp_path / "actions")
    backend = _CaptureBackend(captures)
    actuator = actuator or _Actuator()
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=receipts,
        capture_backend=backend,
        actuator=actuator,
    )
    return perception, receipts, backend, actuator, action


def _click_action(first: dict[str, Any], *, action_id: str = "act-1") -> dict[str, Any]:
    target = _by_name(first, "Submit")
    return {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": target["scope_ref"],
        "action_id": action_id,
        "verb": "click",
        "target_id": target["id"],
        "args": {},
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": first["snapshot"]["snapshot_id"],
        "version_scope": "object",
        "version_precondition": "required",
    }


def test_fresh_exact_guard_dispatches_once_and_appends_running_terminal_receipts(tmp_path: Path) -> None:
    perception, receipts, backend, actuator, action = _stack(tmp_path, [FIXTURES["base"]])
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first))
    assert result["status"] == "ok"
    assert backend.calls == 2  # pre-dispatch + post-dispatch observation
    assert len(actuator.calls) == 1
    assert actuator.calls[0]["verb"] == "click"
    assert actuator.calls[0]["physical_target"].startswith("dom:")
    history = receipts.list_action("s1", "act-1")
    assert [item["receipt_seq"] for item in history] == [1, 2]
    assert [item["status"] for item in history] == ["running", "ok"]
    assert history[0]["after_version"] is None
    assert history[1]["before_version"] == history[0]["before_version"]
    assert history[1]["after_version"] is not None
    assert history[1]["retry"] == {
        "attempt_count": 1,
        "automatic_retry_performed": False,
        "mechanism": None,
        "reason": None,
    }


def test_stale_precondition_rejects_before_dispatch(tmp_path: Path) -> None:
    changed = json.loads(json.dumps(FIXTURES["base"]))
    for node in changed["dom"]["nodes"]:
        if node.get("attributes", {}).get("name") == "Submit":
            node.setdefault("state", {})["enabled"] = False
    perception, receipts, backend, actuator, action = _stack(tmp_path, [changed])
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first))
    assert result["status"] == "rejected"
    assert result["after_version"] is None
    assert len(actuator.calls) == 0
    assert backend.calls == 1
    assert receipts.list_action("s1", "act-1")[0]["receipt_seq"] == 1


def test_same_name_replacement_never_rebinds(tmp_path: Path) -> None:
    replaced = json.loads(json.dumps(FIXTURES["base"]))
    for node in replaced["dom"]["nodes"]:
        if node.get("attributes", {}).get("name") == "Submit":
            node["physical_id"] = "replacement-node"
    perception, _, _, actuator, action = _stack(tmp_path, [replaced])
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first))
    assert result["status"] == "rejected"
    assert len(actuator.calls) == 0


def test_duplicate_action_id_never_dispatches_twice(tmp_path: Path) -> None:
    perception, receipts, _, actuator, action = _stack(tmp_path, [FIXTURES["base"]])
    first = perception.snapshot("s1", FIXTURES["base"])
    request = _click_action(first)
    assert action.execute("s1", request)["status"] == "ok"
    duplicate = action.execute("s1", request)
    assert duplicate["status"] == "rejected"
    assert len(actuator.calls) == 1
    assert [x["receipt_seq"] for x in receipts.list_action("s1", "act-1")] == [1, 2, 3]


def test_actuator_error_is_failed_never_retried_and_post_observation_still_attempted(tmp_path: Path) -> None:
    perception, receipts, backend, actuator, action = _stack(
        tmp_path, [FIXTURES["base"]], actuator=_Actuator(RuntimeError("transport timeout"))
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first))
    assert result["status"] == "failed"
    assert len(actuator.calls) == 1
    assert backend.calls == 2
    assert result["retry"]["automatic_retry_performed"] is False
    assert result["completeness"]["complete"] is False
    assert "dispatch_outcome_ambiguous" in result["completeness"]["reasons"]
    assert [x["status"] for x in receipts.list_action("s1", "act-1")] == ["running", "failed"]


def test_transport_ambiguity_after_partial_effect_reports_observed_side_effect_without_replay(
    tmp_path: Path,
) -> None:
    changed = json.loads(json.dumps(FIXTURES["base"]))
    for source in ("dom", "ax"):
        for node in changed[source]["nodes"]:
            if node.get("physical_id") == "n-submit":
                node.setdefault("state", {})["enabled"] = False
    perception, receipts, backend, actuator, action = _stack(
        tmp_path,
        [FIXTURES["base"], changed],
        actuator=_Actuator(TimeoutError("ack lost after dispatch")),
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first, action_id="partial-effect"))

    assert result["status"] == "failed"
    assert len(actuator.calls) == 1
    assert backend.calls == 2
    assert result["after_version"] is not None
    assert result["observed_effects"]["diff_ref"] is not None
    assert result["observed_effects"]["provisional"] is True
    assert result["retry"]["automatic_retry_performed"] is False
    assert "dispatch_outcome_ambiguous" in result["completeness"]["reasons"]
    assert [x["status"] for x in receipts.list_action("s1", "partial-effect")] == [
        "running",
        "failed",
    ]


def test_session_fence_blocks_receipt_history(tmp_path: Path) -> None:
    perception, receipts, _, _, action = _stack(tmp_path, [FIXTURES["base"]])
    first = perception.snapshot("s1", FIXTURES["base"])
    assert action.execute("s1", _click_action(first))["status"] == "ok"
    assert receipts.list_action("s2", "act-1") == []


def test_receipt_does_not_persist_sensitive_fill_plaintext(tmp_path: Path) -> None:
    perception, receipts, _, actuator, action = _stack(tmp_path, [FIXTURES["base"]])
    first = perception.snapshot("s1", FIXTURES["base"])
    target = _by_name(first, "Submit")
    req = {
        "schema": "smc.semantic_action.v0.1",
        "domain": "browser",
        "scope_ref": target["scope_ref"],
        "action_id": "act-fill",
        "verb": "fill",
        "target_id": target["id"],
        "args": {"text": "secret-value-123", "mode": "replace"},
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": first["snapshot"]["snapshot_id"],
        "version_scope": "object",
        "version_precondition": "required",
    }
    result = action.execute("s1", req)
    assert result["status"] == "ok"
    raw = json.dumps(receipts.list_action("s1", "act-fill"))
    assert "secret-value-123" not in raw
    assert actuator.calls[0]["args"]["text"] == "secret-value-123"


def test_contract_mismatch_rejected_before_capture(tmp_path: Path) -> None:
    perception, _, backend, actuator, action = _stack(tmp_path, [FIXTURES["base"]])
    first = perception.snapshot("s1", FIXTURES["base"])
    req = _click_action(first)
    req["idempotency_class"] = "idempotent"
    result = action.execute("s1", req)
    assert result["status"] == "rejected"
    assert backend.calls == 0
    assert len(actuator.calls) == 0


def test_all_five_frozen_verbs_accept_only_profile_version_scopes(tmp_path: Path) -> None:
    perception, _, _, actuator, action = _stack(tmp_path, [FIXTURES["base"]])
    first = perception.snapshot("s1", FIXTURES["base"])
    target = _by_name(first, "Submit")
    page = next(scope for scope in first["scope_facts"] if scope["kind"] == "page")
    cases = [
        ("click", {}, target["id"], target["scope_ref"], "object"),
        ("fill", {"text": "x", "mode": "replace"}, target["id"], target["scope_ref"], "object"),
        ("select", {"value": "v"}, target["id"], target["scope_ref"], "object"),
        ("navigate", {"url": "http://127.0.0.1/example"}, page["scope_ref"], page["scope_ref"], "resource"),
        ("scroll", {"delta_pages": 1}, target["id"], target["scope_ref"], "object"),
    ]
    for index, (verb, args, target_id, scope_ref, version_scope) in enumerate(cases):
        req = {
            "schema": "smc.semantic_action.v0.1",
            "domain": "browser",
            "scope_ref": scope_ref,
            "action_id": f"act-{verb}-{index}",
            "verb": verb,
            "target_id": target_id,
            "args": args,
            "operation_class": "mutate",
            "idempotency_class": "unknown",
            "atomicity_class": "single_dispatch",
            "expected_version": first["snapshot"]["snapshot_id"],
            "version_scope": version_scope,
            "version_precondition": "required",
        }
        result = action.execute("s1", req)
        assert result["status"] == "ok", (verb, result)
    assert [call["verb"] for call in actuator.calls] == [x[0] for x in cases]


def test_receipts_use_exact_closed_canonical_field_set(tmp_path: Path) -> None:
    perception, receipts, _, _, action = _stack(tmp_path, [FIXTURES["base"]])
    first = perception.snapshot("s1", FIXTURES["base"])
    action.execute("s1", _click_action(first))
    expected = {
        "schema", "domain", "scope_ref", "action_id", "receipt_id", "receipt_seq",
        "verb", "operation_class", "idempotency_class", "atomicity_class", "target_id",
        "status", "before_version", "after_version", "observed_effects", "boundary_events",
        "grounding_refs", "completeness", "predicate_result", "retry",
    }
    for receipt in receipts.list_action("s1", "act-1"):
        assert set(receipt) == expected
        assert receipt["schema"] == "smc.action_receipt.v0.1"
        assert receipt["domain"] == "browser"
        assert set(receipt["observed_effects"]) == {"diff_ref", "scope_transition_ref", "provisional"}
        assert set(receipt["grounding_refs"]) == {"before", "after", "dispatch"}
        assert set(receipt["completeness"]) == {"complete", "reasons"}
        assert set(receipt["retry"]) == {"attempt_count", "automatic_retry_performed", "mechanism", "reason"}


def test_navigation_rejects_script_and_local_file_schemes_before_capture(tmp_path: Path) -> None:
    perception, _, backend, actuator, action = _stack(tmp_path, [FIXTURES["base"]])
    first = perception.snapshot("s1", FIXTURES["base"])
    page = next(scope for scope in first["scope_facts"] if scope["kind"] == "page")
    for index, url in enumerate(("javascript:alert(1)", "file:///etc/passwd", "data:text/html,x")):
        req = {
            "schema": "smc.semantic_action.v0.1", "domain": "browser",
            "scope_ref": page["scope_ref"], "action_id": f"bad-nav-{index}",
            "verb": "navigate", "target_id": page["scope_ref"], "args": {"url": url},
            "operation_class": "mutate", "idempotency_class": "unknown",
            "atomicity_class": "single_dispatch", "expected_version": first["snapshot"]["snapshot_id"],
            "version_scope": "resource", "version_precondition": "required",
        }
        result = action.execute("s1", req)
        assert result["status"] == "rejected"
    assert backend.calls == 0
    assert actuator.calls == []


def test_snapshot_scope_still_requires_exact_target_scope(tmp_path: Path) -> None:
    perception, _, backend, actuator, action = _stack(tmp_path, [FIXTURES["base"]])
    first = perception.snapshot("s1", FIXTURES["base"])
    req = _click_action(first, action_id="scope-mismatch")
    req["version_scope"] = "snapshot"
    req["scope_ref"] = next(scope["scope_ref"] for scope in first["scope_facts"] if scope["kind"] == "page")
    result = action.execute("s1", req)
    assert result["status"] == "rejected"
    assert any(
        reason.startswith("version_precondition_") or reason == "target_scope_mismatch"
        for reason in result["completeness"]["reasons"]
    )
    assert backend.calls == 1
    assert actuator.calls == []


def test_dispatch_grounding_is_durable_session_fenced_and_privacy_safe(tmp_path: Path) -> None:
    perception, receipts, _, _, action = _stack(tmp_path, [FIXTURES["base"]])
    first = perception.snapshot("s1", FIXTURES["base"])
    req = _click_action(first, action_id="grounded")
    result = action.execute("s1", req)
    assert result["status"] == "ok"
    ref = result["grounding_refs"]["dispatch"]
    assert ref.startswith("grounding://browser-action/v0.1/")
    doc = receipts.hydrate_dispatch_grounding("s1", "grounded")
    assert doc is not None
    assert doc["verb"] == "click"
    assert doc["physical_target_sha256"]
    assert "physical_target" not in doc
    assert receipts.hydrate_dispatch_grounding("s2", "grounded") is None


def test_navigate_requires_exact_page_semantic_root_even_for_snapshot_scope(tmp_path: Path) -> None:
    perception, _, _, actuator, action = _stack(tmp_path, [FIXTURES["base"]])
    first = perception.snapshot("s1", FIXTURES["base"])
    target = _by_name(first, "Submit")
    req = {
        "schema": "smc.semantic_action.v0.1", "domain": "browser",
        "scope_ref": first["snapshot"]["scope"]["scope_ref"], "action_id": "bad-nav-target",
        "verb": "navigate", "target_id": target["id"], "args": {"url": "http://127.0.0.1/a"},
        "operation_class": "mutate", "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch", "expected_version": first["snapshot"]["snapshot_id"],
        "version_scope": "snapshot", "version_precondition": "required",
    }
    result = action.execute("s1", req)
    assert result["status"] == "rejected"
    assert any(
        reason.startswith("version_precondition_") or reason == "navigate_page_target_mismatch"
        for reason in result["completeness"]["reasons"]
    )
    assert actuator.calls == []
