"""FR-1 local semantic guard (DESIGN-20261007-browser-semantic-guard) M2 tests.

Covers: baseline derivation+persistency, sentinel-only sensitive contribution,
assess_guard full rejection taxonomy, executor wiring (pre-capture short
circuit, mismatch exemption, guard-off regression).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_loop.browser.action import BrowserActionAdapter, BrowserActionReceiptStore
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)


def _by_name(result: dict[str, Any], name: str) -> dict[str, Any]:
    return next(obj for obj in result["objects"] if obj.get("attributes", {}).get("name") == name)


def _capture(dom_nodes: list[dict[str, Any]], url: str = "https://guard.test/page") -> dict[str, Any]:
    return {
        "schema": "browser.capture.v0.1",
        "page_token": "pt-guard",
        "document_token": "dt-guard",
        "observed_at": 1_000.0,
        "url": url,
        "frames": [{"frame_token": "f-main", "url": url, "parent_frame_token": None}],
        "dom": {"nodes": dom_nodes, "capture_token": "cap-guard"},
        "ax": {"nodes": []},
    }


def _dom_node(
    physical_id: str,
    tag: str,
    *,
    parent: str | None = None,
    name: str | None = None,
    role: str | None = None,
    input_type: str | None = None,
    value_text: str | None = None,
    text: str | None = None,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {"tag": tag}
    if name is not None:
        attributes["name"] = name
    if role is not None:
        attributes["role"] = role
    if input_type is not None:
        attributes["input_type"] = input_type
    if value_text is not None:
        attributes["value_text"] = value_text
    if text is not None:
        attributes["text"] = text
    return {
        "physical_id": physical_id,
        "parent_id": parent,
        "frame_token": "f-main",
        "attributes": attributes,
        "state": {"exists": True},
    }


# ---------------------------------------------------------------------------
# Baseline derivation and persistence
# ---------------------------------------------------------------------------


def test_baseline_is_persisted_per_stable_dom_object(tmp_path: Path) -> None:
    adapter = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "p"))
    snap = adapter.snapshot("s1", FIXTURES["base"])
    submit = _by_name(snap, "Submit")
    bundle, load_error = adapter.store._load(snap["snapshot"]["snapshot_id"])
    assert load_error is None
    baseline = bundle["guard_baseline"]
    entry = baseline[submit["id"]]
    assert entry["schema"] == "smc.browser_guard_baseline.v0.1"
    # identity/dom share the sensor physical-id namespace verbatim
    assert entry["physical_id"] == "n-submit"
    for layer in ("document", "target", "neighborhood"):
        assert isinstance(entry[layer], str) and len(entry[layer]) == 64
    # fixture has no form/dialog/tr/li ancestor -> neighborhood is the
    # canonical empty-neighborhood hash, identical across objects
    assert entry["neighborhood"] == baseline[_by_name(snap, "Cancel")["id"]]["neighborhood"]
    assert entry["target_facts"]["tag"] == "button"
    assert entry["target_facts"]["name"] == "Submit"
    # tamper-evidence: bundle_sha256 must cover guard_baseline (a rewritten
    # baseline must never verify), while content_sha256 stays derived from the
    # canonicalized observation only.
    from llm_loop.browser.perception import _sha256

    payload = {k: v for k, v in bundle.items() if k != "bundle_sha256"}
    assert bundle["bundle_sha256"] == _sha256(payload)
    # sensitive-value discipline: no fixture carries secrets here, but the
    # baseline must never embed raw text beyond non-sensitive target facts
    assert "Submit" in json.dumps(entry)  # diagnostic facts only


def test_sensitive_values_enter_baseline_only_as_sentinel(tmp_path: Path) -> None:
    store_a = BrowserPerceptionStore(tmp_path / "a")
    store_b = BrowserPerceptionStore(tmp_path / "b")
    url = "https://guard.test/login"

    def capture_with(secret: str) -> dict[str, Any]:
        return _capture(
            [
                _dom_node("n-root", "html", name="Login"),
                _dom_node(
                    "n-pass",
                    "input",
                    parent="n-root",
                    name="Password",
                    role="textbox",
                    input_type="password",
                    value_text=secret,
                ),
                _dom_node("n-go", "button", parent="n-root", name="Go", text="Go"),
            ],
            url=url,
        )

    snap_a = BrowserPerceptionAdapter(store=store_a).snapshot("s1", capture_with("s3cret-one"))
    snap_b = BrowserPerceptionAdapter(store=store_b).snapshot("s1", capture_with("different-two"))
    pass_id_a = _by_name(snap_a, "Password")["id"]
    pass_id_b = _by_name(snap_b, "Password")["id"]
    bundle_a, _ = store_a._load(snap_a["snapshot"]["snapshot_id"])
    bundle_b, _ = store_b._load(snap_b["snapshot"]["snapshot_id"])
    # sensor redaction already replaced the value; the target-layer hash is
    # therefore secret-independent
    assert bundle_a["guard_baseline"][pass_id_a]["target"] == (
        bundle_b["guard_baseline"][pass_id_b]["target"]
    )
    dumped = json.dumps(bundle_a["guard_baseline"])
    assert "s3cret-one" not in dumped and "different-two" not in dumped


# ---------------------------------------------------------------------------
# assess_guard taxonomy
# ---------------------------------------------------------------------------


def _submit_raw(**overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "ok": True,
        "doc": {"url": "https://example.test/a"},
        "target": {
            "tag": "button",
            "name": "Submit",
            "role": "button",
            "type": None,
            "text": "Submit",
            "value": None,
        },
        "nb": None,
        "geo": {"w": 120.0, "h": 32.0, "visible": True},
        "occluded": False,
        "hitTag": "button",
    }
    raw.update(overrides)
    return raw


def _baseline_for(tmp_path: Path) -> tuple[BrowserPerceptionAdapter, dict[str, Any], str]:
    adapter = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "p"))
    snap = adapter.snapshot("s1", FIXTURES["base"])
    submit = _by_name(snap, "Submit")
    baseline = adapter.guard_baseline("s1", snap["snapshot"]["snapshot_id"], submit["id"])
    assert isinstance(baseline, dict)
    return adapter, baseline, submit["id"]


def test_guard_pass_on_aligned_probe(tmp_path: Path) -> None:
    adapter, baseline, _ = _baseline_for(tmp_path)
    verdict = adapter.assess_guard(baseline=baseline, raw=_submit_raw())
    assert verdict["verdict"] == "pass"
    assert verdict["reason"] is None
    assert verdict["occluded"] is False
    assert verdict["observed"]["geo"]["visible"] is True


def test_guard_detach_on_resolve_miss(tmp_path: Path) -> None:
    adapter, baseline, _ = _baseline_for(tmp_path)
    verdict = adapter.assess_guard(baseline=baseline, raw={"ok": False, "stage": "resolve"})
    assert verdict["verdict"] == "reject"
    assert verdict["reason"] == "guard_detach"


def test_guard_timeout_on_evaluate_miss_and_shape_errors(tmp_path: Path) -> None:
    adapter, baseline, _ = _baseline_for(tmp_path)
    for raw in ({"ok": False, "stage": "evaluate"}, {"ok": False}, "not-a-dict"):
        verdict = adapter.assess_guard(baseline=baseline, raw=raw)  # type: ignore[arg-type]
        assert verdict["verdict"] == "reject"
        assert verdict["reason"] == "guard_timeout"


def test_guard_occluded_by_point_hit_and_zero_size(tmp_path: Path) -> None:
    adapter, baseline, _ = _baseline_for(tmp_path)
    banner = _submit_raw(occluded=True, hitTag="div")
    verdict = adapter.assess_guard(baseline=baseline, raw=banner)
    assert verdict["verdict"] == "reject"
    assert verdict["reason"] == "guard_occluded"
    assert verdict["occluded"] is True

    zero = _submit_raw(geo={"w": 0.0, "h": 0.0, "visible": False}, hitTag="button")
    verdict = adapter.assess_guard(baseline=baseline, raw=zero)
    assert verdict["verdict"] == "reject"
    assert verdict["reason"] == "guard_occluded"


def test_guard_layer_mismatch_taxonomy(tmp_path: Path) -> None:
    adapter, baseline, _ = _baseline_for(tmp_path)
    renamed = _submit_raw()
    renamed["target"] = {**renamed["target"], "name": "Submit now"}
    verdict = adapter.assess_guard(baseline=baseline, raw=renamed)
    assert verdict["verdict"] == "reject"
    assert verdict["reason"] == "guard_document_changed:layer=target"
    assert verdict["mismatched_layer"] == "target"

    moved = _submit_raw(doc={"url": "https://example.test/other"})
    verdict = adapter.assess_guard(baseline=baseline, raw=moved)
    assert verdict["reason"] == "guard_document_changed:layer=document"

    reformed = _submit_raw(
        nb={"tag": "form", "role": None, "children": [{"tag": "button", "name": "Submit", "text": "Submit"}]}
    )
    verdict = adapter.assess_guard(baseline=baseline, raw=reformed)
    assert verdict["reason"] == "guard_document_changed:layer=neighborhood"


def test_sensitive_probe_value_aligns_with_baseline_sentinel(tmp_path: Path) -> None:
    adapter = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "p"))
    capture = _capture(
        [
            _dom_node("n-root", "html", name="Login"),
            _dom_node(
                "n-pass",
                "input",
                parent="n-root",
                name="Password",
                role="textbox",
                input_type="password",
                # sensor already stored the sentinel as value_text
                value_text="<redacted>",
            ),
        ]
    )
    snap = adapter.snapshot("s1", capture)
    target = _by_name(snap, "Password")
    baseline = adapter.guard_baseline("s1", snap["snapshot"]["snapshot_id"], target["id"])
    assert isinstance(baseline, dict)
    # live probe reports the raw attribute value; assess_guard must redact it
    # through the SAME FR-6 whitelist before hashing -> pass, no secret leak
    raw = {
        "ok": True,
        "doc": {"url": "https://guard.test/page"},
        "target": {
            "tag": "input",
            "name": "Password",
            "role": "textbox",
            "type": "password",
            "text": None,
            "value": "hunter2-live",
        },
        "nb": None,
        "geo": {"w": 180.0, "h": 24.0, "visible": True},
        "occluded": False,
        "hitTag": "input",
    }
    verdict = adapter.assess_guard(baseline=baseline, raw=raw)
    assert verdict["verdict"] == "pass", verdict
    assert "hunter2-live" not in json.dumps(verdict)


def test_guard_baseline_load_guards_session_and_missing_entries(tmp_path: Path) -> None:
    adapter = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "p"))
    snap = adapter.snapshot("s1", FIXTURES["base"])
    submit_id = _by_name(snap, "Submit")["id"]
    snap_version = snap["snapshot"]["snapshot_id"]
    assert adapter.guard_baseline("s1", snap_version, submit_id) is not None
    # wrong session -> None (version mechanism stays the sole gate)
    assert adapter.guard_baseline("other", snap_version, submit_id) is None
    # missing object -> None
    assert adapter.guard_baseline("s1", snap_version, "obj-nonexistent") is None
    # missing bundle -> None
    assert adapter.guard_baseline("s1", "bsnap-1-deadbeefdeadbeef", submit_id) is None


# ---------------------------------------------------------------------------
# Executor wiring
# ---------------------------------------------------------------------------


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
    def __init__(self) -> None:
        from llm_loop.browser.action import BrowserDispatchResult

        self.calls: list[dict[str, Any]] = []
        self._result = BrowserDispatchResult(
            acknowledged=True,
            boundary_events=(),
            completeness_reasons=("boundary_detector_non_exhaustive",),
        )

    def dispatch(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._result


def _stack(tmp_path: Path, captures: list[dict[str, Any]], *, guard_collector=None, guard_enabled=False):
    perception = BrowserPerceptionAdapter(store=BrowserPerceptionStore(tmp_path / "perception"))
    receipts = BrowserActionReceiptStore(tmp_path / "actions")
    backend = _CaptureBackend(captures)
    actuator = _Actuator()
    action = BrowserActionAdapter(
        perception=perception,
        receipt_store=receipts,
        capture_backend=backend,
        actuator=actuator,
        guard_collector=guard_collector,
        guard_enabled=guard_enabled,
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
        "args_normalization": {"applied": False, "rule": None},
        "operation_class": "mutate",
        "idempotency_class": "unknown",
        "atomicity_class": "single_dispatch",
        "expected_version": first["snapshot"]["snapshot_id"],
        "version_scope": "object",
        "version_precondition": "required",
    }


def test_guard_pass_exempts_version_mismatch_and_receipt_carries_verdict(tmp_path: Path) -> None:
    # before-capture observes a DIFFERENT page state -> version mismatch; the
    # guard collector reports the target's neighborhood unchanged (animation/
    # ad rotation elsewhere) -> exemption must dispatch exactly once.
    perception, receipts, backend, actuator, action = _stack(
        tmp_path,
        [FIXTURES["push_state"], FIXTURES["push_state"]],
        guard_collector=lambda physical: _submit_raw(doc={"url": "https://example.test/a"}),
        guard_enabled=True,
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first))
    assert result["status"] == "ok", result
    assert len(actuator.calls) == 1
    assert result["guard"]["verdict"] == "pass"
    assert result["guard"]["schema"] == "smc.browser_guard_verdict.v0.1"


def test_guard_rejection_short_circuits_before_capture(tmp_path: Path) -> None:
    def collector(physical: str) -> dict[str, Any]:
        return {"ok": False, "stage": "resolve"}

    perception, receipts, backend, actuator, action = _stack(
        tmp_path, [FIXTURES["base"]], guard_collector=collector, guard_enabled=True
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first))
    assert result["status"] == "rejected"
    assert result["completeness"]["reasons"] == ["guard_detach"]
    assert backend.calls == 0  # guard fired before any capture
    assert actuator.calls == []
    assert result["guard"]["reason"] == "guard_detach"


def test_guard_channel_exception_fails_closed_as_timeout(tmp_path: Path) -> None:
    def collector(physical: str) -> dict[str, Any]:
        raise RuntimeError("cdp socket died")

    perception, receipts, backend, actuator, action = _stack(
        tmp_path, [FIXTURES["base"]], guard_collector=collector, guard_enabled=True
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first))
    assert result["status"] == "rejected"
    assert result["completeness"]["reasons"] == ["guard_timeout:RuntimeError"]


def test_guard_disabled_keeps_premutation_semantics(tmp_path: Path) -> None:
    # guard_enabled=False + version mismatch -> rejected exactly as before FR-1
    perception, receipts, backend, actuator, action = _stack(
        tmp_path, [FIXTURES["push_state"], FIXTURES["push_state"]], guard_enabled=False
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first))
    assert result["status"] == "rejected"
    assert any(
        str(r).startswith("version_precondition_") for r in result["completeness"]["reasons"]
    )
    assert "guard" not in result or result.get("guard") is None


def test_guard_enabled_but_no_collector_is_inert(tmp_path: Path) -> None:
    perception, receipts, backend, actuator, action = _stack(
        tmp_path, [FIXTURES["base"]], guard_collector=None, guard_enabled=True
    )
    first = perception.snapshot("s1", FIXTURES["base"])
    result = action.execute("s1", _click_action(first))
    assert result["status"] == "ok"
    assert "guard" not in result
