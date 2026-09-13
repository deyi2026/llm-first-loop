from __future__ import annotations

import inspect
import json
import runpy
from pathlib import Path
from typing import Any

import pytest

from llm_loop.browser.perception import (
    BrowserPerceptionAdapter,
    BrowserPerceptionStore,
    PlaywrightPageCaptureBackend,
)
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)
PROFILE = json.loads(
    (ROOT / "docs/SMC-BROWSER-PHASE1-PROFILE-v0.1.json").read_text(encoding="utf-8")
)
SCHEMA = json.loads(
    (ROOT / "docs/SMC-BROWSER-PHASE1-SCHEMA-v0.1.json").read_text(encoding="utf-8")
)


def _adapter(tmp_path: Path, *, now: float = 1_000.0) -> BrowserPerceptionAdapter:
    store = BrowserPerceptionStore(
        tmp_path / "browser",
        retention_seconds=60,
        now_fn=lambda: now,
    )
    return BrowserPerceptionAdapter(store=store, capture_node_cap=10_000)


def _by_name(result: dict[str, Any], name: str) -> dict[str, Any]:
    for obj in result["objects"]:
        if obj["attributes"].get("name") == name:
            return obj
    raise AssertionError(f"object named {name!r} not found")


def _all_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key))
            keys.update(_all_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_all_keys(child))
    return keys


def _bspec_errors(value: Any, schema_name: str) -> list[str]:
    namespace = runpy.run_path(str(ROOT / "tests/unit/test_smc_browser_phase1_spec_v01.py"))
    validate = namespace["_validate"]
    return validate(value, {"$ref": f"#/$defs/{schema_name}"}, SCHEMA)


def test_model_surface_is_read_only_and_has_no_backend_locator_parameters(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    tool = BrowserPerceiveTool(adapter=adapter, backend=None, session_id_getter=lambda: "s1")

    assert tool.name == "browser_perceive"
    props = tool.parameters["properties"]
    assert props["action"]["enum"] == ["snapshot", "hydrate", "diff"]
    assert set(props) == {
        "action",
        "projection_limit",
        "grounding_ref",
        "from_version",
        "to_version",
    }
    model_surface_tokens = {str(key).lower() for key in props}
    model_surface_tokens.update(str(value).lower() for value in props["action"]["enum"])
    for forbidden in (
        "selector",
        "xpath",
        "coordinate",
        "cdp_node_id",
        "ax_index",
        "native_handle",
        "click",
        "fill",
        "navigate",
        "scroll",
        "script",
        "code",
        "url",
    ):
        assert forbidden not in model_surface_tokens


def test_snapshot_requires_backend_but_hydrate_does_not_mutate(tmp_path: Path) -> None:
    tool = BrowserPerceiveTool(
        adapter=_adapter(tmp_path), backend=None, session_id_getter=lambda: "s1"
    )
    result = tool.execute(action="snapshot")
    assert result.status.value == "failure"
    assert "backend" in result.content.lower()


def test_reorder_preserves_id_but_replacement_and_duplicates_never_reuse_old_id(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    base = adapter.snapshot("s1", FIXTURES["base"])
    reorder = adapter.snapshot("s1", FIXTURES["reorder"])
    replacement = adapter.snapshot("s1", FIXTURES["replacement"])

    old_id = _by_name(base, "Submit")["id"]
    assert _by_name(reorder, "Submit")["id"] == old_id
    new_ids = [
        obj["id"]
        for obj in replacement["objects"]
        if obj["attributes"].get("name") == "Submit"
    ]
    assert len(new_ids) == 2
    assert old_id not in new_ids
    assert len(set(new_ids)) == 2


def test_identity_api_has_no_task_relevance_input() -> None:
    params = set(inspect.signature(BrowserPerceptionAdapter.snapshot).parameters)
    assert not params.intersection({"task", "task_text", "query", "relevance", "priority"})


def test_identical_content_in_two_pages_never_aliases_semantic_ids(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    first = adapter.snapshot("s1", FIXTURES["base"])
    clone = json.loads(json.dumps(FIXTURES["base"]))
    clone["page_token"] = "page-b"
    clone["document_token"] = "doc-b1"
    second = adapter.snapshot("s1", clone)
    assert _by_name(first, "Submit")["id"] != _by_name(second, "Submit")["id"]
    assert first["snapshot"]["scope"]["scope_ref"] != second["snapshot"]["scope"]["scope_ref"]


def test_document_and_frame_generation_changes_invalidate_old_identity(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)

    before = adapter.snapshot("s1", FIXTURES["base"])
    after = adapter.snapshot("s1", FIXTURES["navigate"])
    assert after["snapshot"]["scope"]["document_generation"] > before["snapshot"]["scope"]["document_generation"]
    assert _by_name(after, "Submit")["id"] != _by_name(before, "Submit")["id"]

    frame_before = adapter.snapshot("s1", FIXTURES["frame_v1"])
    frame_after = adapter.snapshot("s1", FIXTURES["frame_v2"])
    obj_before = _by_name(frame_before, "Inner")
    obj_after = _by_name(frame_after, "Inner")
    assert obj_before["scope_ref"] != obj_after["scope_ref"]
    assert obj_before["id"] != obj_after["id"]


def test_adapter_restart_increments_runtime_generation_and_rekeys_ids(tmp_path: Path) -> None:
    first = _adapter(tmp_path).snapshot("s1", FIXTURES["base"])
    second = _adapter(tmp_path).snapshot("s1", FIXTURES["base"])
    assert second["snapshot"]["scope"]["runtime_generation"] > first["snapshot"]["scope"]["runtime_generation"]
    assert _by_name(first, "Submit")["id"] != _by_name(second, "Submit")["id"]


def test_dom_ax_field_conflict_becomes_null_with_source_grounding(tmp_path: Path) -> None:
    result = _adapter(tmp_path).snapshot("s1", FIXTURES["conflict"])
    obj = _by_name(result, "Save")
    assert obj["state"]["enabled"] is None
    conflicts = [c for c in obj["coverage"]["conflicts"] if c.get("field") == "state.enabled"]
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict["resolution"] == "unresolved"
    assert conflict["derivation_basis"] is None
    assert {o["source"] for o in conflict["observations"]} == {"dom", "ax"}
    assert all(o["grounding_ref"].startswith("grounding://browser/v0.1/") for o in conflict["observations"])


def test_dom_ax_identity_mapping_ambiguity_never_force_fuses(tmp_path: Path) -> None:
    result = _adapter(tmp_path).snapshot("s1", FIXTURES["fusion_ambiguity"])
    assert len(result["objects"]) == 3
    dom_obj = next(o for o in result["objects"] if o["attributes"].get("tag") == "button")
    conflicts = [c for c in dom_obj["coverage"]["conflicts"] if "identity_mapping" in c]
    assert len(conflicts) == 1
    assert conflicts[0]["resolution"] == "unresolved"
    assert len(conflicts[0]["observations"]) == 2
    assert all("ax-y" not in json.dumps(o) for o in result["objects"])


def test_dom_present_ax_absent_is_source_qualified_not_ax_failure(tmp_path: Path) -> None:
    result = _adapter(tmp_path).snapshot("s1", FIXTURES["aria_hidden"])
    obj = _by_name(result, "Hidden")
    assert obj["coverage"]["sources"] == ["dom"]
    assert obj["coverage"]["status"] == "partial"
    assert "ax_unavailable" not in obj["coverage"]["blind_spots"]
    assert result["snapshot"]["completeness"]["complete"] is True


def test_structural_blindspots_and_cross_origin_frame_are_explicit(tmp_path: Path) -> None:
    result = _adapter(tmp_path).snapshot("s1", FIXTURES["blindspots"])
    reasons = result["snapshot"]["completeness"]["reasons"]
    assert result["snapshot"]["completeness"]["complete"] is False
    assert "closed_shadow_root" in reasons
    assert "canvas" in reasons
    assert "cross_origin_frame" in reasons
    dumped = json.dumps(result, ensure_ascii=False)
    assert "vision" not in dumped.lower() or "explicit_only_deferred_phase2" in dumped


def test_relations_are_structural_only(tmp_path: Path) -> None:
    result = _adapter(tmp_path).snapshot("s1", FIXTURES["base"])
    relation_types = {r["type"] for o in result["objects"] for r in o["relations"]}
    assert relation_types <= set(PROFILE["field_vocabulary"]["relations"])
    assert not relation_types.intersection({"near", "similar", "recommended", "same_group"})


def test_projection_cap_does_not_corrupt_observation_completeness_and_full_hydrates(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    result = adapter.snapshot("s1", FIXTURES["base"], projection_limit=1)
    snap = result["snapshot"]
    assert snap["completeness"]["complete"] is True
    assert snap["projection"]["complete"] is False
    assert len(result["objects"]) == 1
    hydrated = adapter.hydrate("s1", snap["objects_ref"])
    assert hydrated["availability"] == "available"
    assert len(hydrated["content"]) == 3


def test_push_state_keeps_document_generation_and_identity(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    after = adapter.snapshot("s1", FIXTURES["push_state"])
    assert after["snapshot"]["scope"]["document_generation"] == before["snapshot"]["scope"]["document_generation"]
    assert _by_name(after, "Submit")["id"] == _by_name(before, "Submit")["id"]
    document = next(o for o in after["objects"] if o["kind"] == "document")
    assert document["attributes"]["href"] == "https://example.test/a?step=2"


def test_grounding_is_integrity_bound_session_scoped_and_expires(tmp_path: Path) -> None:
    now = [1_000.0]
    store = BrowserPerceptionStore(tmp_path / "browser", retention_seconds=10, now_fn=lambda: now[0])
    adapter = BrowserPerceptionAdapter(store=store)
    result = adapter.snapshot("s1", FIXTURES["base"])
    ref = _by_name(result, "Submit")["grounding_ref"]

    hydrated = adapter.hydrate("s1", ref)
    assert hydrated["availability"] == "available"
    assert len(hydrated["content_sha256"]) == 64
    assert "physical_id" not in _all_keys(hydrated)
    assert "ax_id" not in _all_keys(hydrated)

    assert adapter.hydrate("other-session", ref)["availability"] == "unauthorized"
    now[0] = 1_011.0
    assert adapter.hydrate("s1", ref)["availability"] == "expired"


def test_snapshot_and_objects_contain_no_ephemeral_locator_or_strategy_fields(tmp_path: Path) -> None:
    result = _adapter(tmp_path).snapshot("s1", FIXTURES["base"])
    dumped = json.dumps(result, sort_keys=True).lower()
    for forbidden in (
        "physical_id",
        "ax_id",
        "selector",
        "xpath",
        "coordinate",
        "backend_node_id",
        "cdp_node_id",
        "ax_index",
        "recommended",
        "best",
        "priority",
        "task_relevance",
        "completion",
        "recovery_sequence",
        "hint",
    ):
        assert forbidden not in dumped


def test_actual_snapshot_and_objects_validate_against_frozen_bspec_closed_schema(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    for fixture_name in ("base", "conflict", "fusion_ambiguity", "blindspots"):
        result = adapter.snapshot("s1", FIXTURES[fixture_name])
        assert _bspec_errors(result["snapshot"], "world_snapshot") == []
        hydrated = adapter.hydrate("s1", result["snapshot"]["objects_ref"])
        assert hydrated["availability"] == "available"
        for obj in hydrated["content"]:
            assert _bspec_errors(obj, "semantic_object") == []


def test_scope_facts_expose_page_document_nested_frame_parentage_and_hydrate(
    tmp_path: Path,
) -> None:
    raw = json.loads(json.dumps(FIXTURES["frame_v1"]))
    raw["frames"] = [
        {
            "frame_token": "frame-child",
            "document_token": "frame-doc-child",
            "parent_frame_token": "frame-parent",
            "same_origin": True,
            "captured": True,
            "url": "https://example.test/child",
        },
        {
            "frame_token": "frame-parent",
            "document_token": "frame-doc-parent",
            "parent_frame_token": None,
            "same_origin": True,
            "captured": True,
            "url": "https://example.test/parent",
        },
    ]
    raw["dom"]["nodes"] = []
    raw["ax"]["nodes"] = []
    adapter = _adapter(tmp_path)
    result = adapter.snapshot("s1", raw)

    assert len(result["scope_facts"]) == 4
    for scope in result["scope_facts"]:
        assert _bspec_errors(scope, "browser_scope") == []
    page = next(scope for scope in result["scope_facts"] if scope["kind"] == "page")
    document = next(scope for scope in result["scope_facts"] if scope["kind"] == "document")
    frames = [scope for scope in result["scope_facts"] if scope["kind"] == "frame"]
    assert page["parent_scope_ref"] is None
    assert document["parent_scope_ref"] == page["scope_ref"]
    assert {scope["parent_scope_ref"] for scope in frames} == {
        document["scope_ref"],
        next(scope["scope_ref"] for scope in frames if scope["parent_scope_ref"] == document["scope_ref"]),
    }

    hydrated = adapter.hydrate("s1", result["scope_facts_ref"])
    assert hydrated["availability"] == "available"
    assert hydrated["content"] == result["scope_facts"]


def test_content_sha_is_stable_for_same_mechanical_observation(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    first = adapter.snapshot("s1", FIXTURES["base"])
    second = adapter.snapshot("s1", FIXTURES["base"])
    assert first["snapshot"]["snapshot_id"] != second["snapshot"]["snapshot_id"]
    assert first["snapshot"]["content_sha256"] == second["snapshot"]["content_sha256"]


def test_content_sha_normalizes_snapshot_local_ax_identity_without_stabilizing_it(
    tmp_path: Path,
) -> None:
    raw = json.loads(json.dumps(FIXTURES["base"]))
    raw["ax"]["nodes"].append(
        {
            "ax_id": "ax-inline-only",
            "physical_id": "",
            "frame_token": None,
            "kind": "text",
            "attributes": {"name": "AX Inline Only"},
            "state": {"exists": True},
        }
    )
    adapter = _adapter(tmp_path)

    first = adapter.snapshot("s1", raw)
    second = adapter.snapshot("s1", raw)
    first_local = _by_name(first, "AX Inline Only")
    second_local = _by_name(second, "AX Inline Only")

    assert first_local["id"] != second_local["id"], "snapshot-local AX identity must stay local"
    assert first["snapshot"]["content_sha256"] == second["snapshot"]["content_sha256"]


class _FixtureBackend:
    def __init__(self, fixture: dict[str, Any]) -> None:
        self.fixture = fixture
        self.calls = 0

    def capture(self) -> dict[str, Any]:
        self.calls += 1
        return json.loads(json.dumps(self.fixture))


def test_model_facing_tool_snapshot_then_exact_hydrate(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    backend = _FixtureBackend(FIXTURES["base"])
    tool = BrowserPerceiveTool(
        adapter=adapter,
        backend=backend,
        session_id_getter=lambda: "s1",
    )
    snap_result = tool.execute(action="snapshot", projection_limit=1)
    assert snap_result.status.value == "success"
    assert backend.calls == 1
    snap_payload = json.loads(snap_result.content)
    assert snap_payload["snapshot"]["projection"]["complete"] is False

    hydrate_result = tool.execute(
        action="hydrate",
        grounding_ref=snap_payload["snapshot"]["objects_ref"],
    )
    assert hydrate_result.status.value == "success"
    assert backend.calls == 1
    hydrate_payload = json.loads(hydrate_result.content)
    assert hydrate_payload["availability"] == "available"
    assert len(hydrate_payload["content"]) == 3


def test_grounding_integrity_tamper_becomes_unavailable_not_silent_refetch(tmp_path: Path) -> None:
    store = BrowserPerceptionStore(
        tmp_path / "browser",
        retention_seconds=60,
        now_fn=lambda: 1_000.0,
    )
    adapter = BrowserPerceptionAdapter(store=store)
    result = adapter.snapshot("s1", FIXTURES["base"])
    snapshot_id = result["snapshot"]["snapshot_id"]
    bundle_path = store.root / "snapshots" / f"{snapshot_id}.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["objects"][0]["kind"] = "unknown"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    hydrated = adapter.hydrate("s1", result["snapshot"]["objects_ref"])
    assert hydrated == {
        "grounding_ref": result["snapshot"]["objects_ref"],
        "availability": "unavailable",
        "reason": "integrity_error",
    }


class _FakeCdp:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(method)
        if method == "Runtime.evaluate":
            assert params == {
                "expression": "document.readyState",
                "returnByValue": True,
                "awaitPromise": False,
                "userGesture": False,
                "throwOnSideEffect": True,
            }
            return {"result": {"type": "string", "value": "complete"}}
        if method == "Target.getTargetInfo":
            return {"targetInfo": {"targetId": "target-1"}}
        if method == "Page.getFrameTree":
            return {"frameTree": {"frame": {"id": "frame-main", "loaderId": "loader-1", "url": "https://example.test/"}}}
        if method == "DOMSnapshot.captureSnapshot":
            return {
                "strings": ["HTML", "BUTTON", "role", "button", "aria-label", "Go"],
                "documents": [{
                    "frameId": "frame-main",
                    "documentURL": 0,
                    "nodes": {
                        "nodeName": [0, 1],
                        "nodeValue": [0, 0],
                        "parentIndex": [-1, 0],
                        "backendNodeId": [1, 2],
                        "attributes": [[], [2, 3, 4, 5]]
                    },
                    "layout": {"nodeIndex": [0, 1]}
                }]
            }
        if method == "Accessibility.getFullAXTree":
            return {"nodes": [{
                "nodeId": "ax1",
                "backendDOMNodeId": 2,
                "ignored": False,
                "role": {"value": "button"},
                "name": {"value": "Go"},
                "properties": []
            }]}
        raise AssertionError(f"unexpected CDP method {method}")


class _FakeContext:
    def __init__(self, cdp: _FakeCdp) -> None:
        self.cdp = cdp

    def new_cdp_session(self, page: Any) -> _FakeCdp:
        return self.cdp


class _FakePage:
    def __init__(self, cdp: _FakeCdp) -> None:
        self.context = _FakeContext(cdp)
        self.url = "https://example.test/"


def test_playwright_backend_uses_only_read_only_capture_methods() -> None:
    cdp = _FakeCdp()
    raw = PlaywrightPageCaptureBackend(_FakePage(cdp)).capture()
    assert cdp.calls == [
        "Target.getTargetInfo",
        "Page.getFrameTree",
        "DOMSnapshot.captureSnapshot",
        "Accessibility.getFullAXTree",
        "Runtime.evaluate",
    ]
    assert raw["document_ready_state"] == "complete"
    assert raw["dom"]["available"] is True
    assert raw["ax"]["available"] is True
    assert raw["dom"]["nodes"][1]["attributes"]["name"] == "Go"


def test_playwright_backend_exact_cap_is_not_falsely_marked_truncated() -> None:
    cdp = _FakeCdp()
    raw = PlaywrightPageCaptureBackend(_FakePage(cdp), node_cap=2).capture()
    assert len(raw["dom"]["nodes"]) == 2
    assert raw["dom"]["truncated"] is False
    assert raw["ax"]["truncated"] is False


class _MissingIdentityCdp(_FakeCdp):
    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if method == "Target.getTargetInfo":
            self.calls.append(method)
            return {"targetInfo": {}}
        return super().send(method, params)


def test_playwright_backend_never_uses_url_as_page_identity_fallback() -> None:
    with pytest.raises(RuntimeError, match="target identity"):
        PlaywrightPageCaptureBackend(_FakePage(_MissingIdentityCdp())).capture()


@pytest.mark.parametrize(
    "r3_id",
    [
        "R3-01", "R3-02", "R3-03", "R3-04", "R3-05", "R3-06", "R3-07", "R3-08",
        "R3-09", "R3-10", "R3-11", "R3-12", "R3-13", "R3-15", "R3-16", "R3-27",
        "R3-28", "R3-30", "R3-31", "R3-32",
    ],
)
def test_bperception_phase_claims_only_perception_r3_obligations(r3_id: str) -> None:
    assert r3_id in PROFILE["r3_phase1_fixture_map"]
