from __future__ import annotations

import inspect
import json
import runpy
from copy import deepcopy
from pathlib import Path
from typing import Any

from llm_loop.browser import perception as perception_module
from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore
from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)
SCHEMA = json.loads(
    (ROOT / "docs/SMC-BROWSER-PHASE1-SCHEMA-v0.1.json").read_text(encoding="utf-8")
)


def _adapter(tmp_path: Path, *, now: float = 1_000.0) -> BrowserPerceptionAdapter:
    return BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(
            tmp_path / "browser",
            retention_seconds=60,
            now_fn=lambda: now,
        ),
        capture_node_cap=10_000,
    )


def _bspec_errors(value: Any, schema_name: str) -> list[str]:
    namespace = runpy.run_path(str(ROOT / "tests/unit/test_smc_browser_phase1_spec_v01.py"))
    validate = namespace["_validate"]
    return validate(value, {"$ref": f"#/$defs/{schema_name}"}, SCHEMA)


def _snapshot_id(result: dict[str, Any]) -> str:
    return str(result["snapshot"]["snapshot_id"])


def _object_named(result: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [obj for obj in result["objects"] if obj["attributes"].get("name") == name]
    dom_backed = [
        obj
        for obj in matches
        if "dom" in obj.get("coverage", {}).get("sources", [])
    ]
    if len(dom_backed) != 1:
        raise AssertionError(f"expected one DOM-backed object named {name!r}, got {len(dom_backed)}")
    return dom_backed[0]


def _disabled_submit_fixture() -> dict[str, Any]:
    raw = deepcopy(FIXTURES["base"])
    for source in ("dom", "ax"):
        for node in raw[source]["nodes"]:
            if node.get("physical_id") == "n-submit":
                node.setdefault("state", {})["enabled"] = False
    for node in raw["dom"]["nodes"]:
        if node.get("physical_id") == "n-submit":
            node.setdefault("attributes", {})["text"] = "Submit now"
    return raw


def _with_snapshot_local_ax_object() -> dict[str, Any]:
    raw = deepcopy(FIXTURES["base"])
    raw["ax"]["nodes"].append(
        {
            "ax_id": "ax-local-only",
            "physical_id": None,
            "frame_token": None,
            "kind": "text",
            "attributes": {"role": "InlineTextBox", "name": "Local only"},
            "state": {"exists": True},
        }
    )
    return raw


def test_model_surface_keeps_diff_and_aggregated_wait_read_only(tmp_path: Path) -> None:
    tool = BrowserPerceiveTool(
        adapter=_adapter(tmp_path),
        backend=None,
        session_id_getter=lambda: "s1",
    )
    props = tool.parameters["properties"]
    assert props["action"]["enum"] == ["snapshot", "hydrate", "diff", "wait"]
    assert set(props) == {
        "action",
        "projection_limit",
        "projection_kinds",
        "projection_cursor",
        "vision",
        "grounding_ref",
        "from_version",
        "to_version",
        "condition",
        "within_ms",
    }
    surface = {str(key).lower() for key in props}
    surface.update(str(value).lower() for value in props["action"]["enum"])
    for forbidden in (
        "selector",
        "xpath",
        "coordinate",
        "click",
        "fill",
        "select",
        "navigate",
        "reload",
        "scroll",
        "script",
        "code",
        "url",
    ):
        assert forbidden not in surface


def test_diff_api_has_no_task_semantic_input() -> None:
    params = set(inspect.signature(BrowserPerceptionAdapter.diff).parameters)
    assert not params.intersection({"task", "task_text", "query", "relevance", "priority"})


def test_reorder_is_empty_net_diff_and_full_list_ref_hydrates_exactly(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    after = adapter.snapshot("s1", FIXTURES["reorder"])

    diff = adapter.diff("s1", _snapshot_id(before), _snapshot_id(after))

    assert _bspec_errors(diff, "semantic_diff") == []
    assert diff["diff_semantics"] == "snapshot_pair_net"
    assert diff["comparable"] is True
    assert diff["scope_relation"] == "same"
    assert diff["created"] == []
    assert diff["removed"] == []
    assert diff["changed"] == []
    assert diff["completeness"] == {"complete": True, "reasons": []}
    assert diff["field_completeness"] == {
        "created": True,
        "removed": True,
        "changed": True,
    }
    assert isinstance(diff["full_list_ref"], str)
    hydrated = adapter.hydrate("s1", diff["full_list_ref"])
    assert hydrated["availability"] == "available"
    assert hydrated["content"] == diff
    assert adapter.diff("s1", _snapshot_id(before), _snapshot_id(after)) == diff
    assert adapter.hydrate("s1", diff["full_list_ref"])["content"] == diff


def test_diff_grounding_tamper_is_rejected_by_integrity_check(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    after = adapter.snapshot("s1", FIXTURES["reorder"])
    from_version = _snapshot_id(before)
    to_version = _snapshot_id(after)
    diff = adapter.diff("s1", from_version, to_version)

    path = adapter.store.root / "diffs" / f"{from_version}--{to_version}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["canonical_diff"]["reason"] = "tampered"
    path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    hydrated = adapter.hydrate("s1", diff["full_list_ref"])
    assert hydrated["availability"] == "unavailable"
    assert hydrated["reason"] == "integrity_error"


def test_same_document_reports_field_level_changed_lower_noise(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    after = adapter.snapshot("s1", _disabled_submit_fixture())
    old_submit = _object_named(before, "Submit")

    diff = adapter.diff("s1", _snapshot_id(before), _snapshot_id(after))

    assert diff["comparable"] is True
    changed = {item["id"]: item["fields"] for item in diff["changed"]}
    assert old_submit["id"] in changed
    assert changed[old_submit["id"]] == ["attributes.text", "state.enabled"]
    # Per-snapshot grounding_ref/observed_version must never make every object look changed.
    assert len(changed) == 1


def test_replacement_uses_semantic_identity_not_name_similarity(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    after = adapter.snapshot("s1", FIXTURES["replacement"])
    old_submit_id = _object_named(before, "Submit")["id"]
    new_submit_ids = {
        obj["id"]
        for obj in after["objects"]
        if obj["attributes"].get("name") == "Submit"
        and "dom" in obj.get("coverage", {}).get("sources", [])
    }

    diff = adapter.diff("s1", _snapshot_id(before), _snapshot_id(after))

    assert diff["comparable"] is True
    assert old_submit_id in diff["removed"]
    assert new_submit_ids
    assert new_submit_ids.issubset(set(diff["created"]))
    assert old_submit_id not in new_submit_ids


def test_incomplete_observation_suppresses_created_removed_but_keeps_changed_lower_bound(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    partial = _disabled_submit_fixture()
    partial["dom"]["truncated"] = True
    after = adapter.snapshot("s1", partial)
    old_submit = _object_named(before, "Submit")

    diff = adapter.diff("s1", _snapshot_id(before), _snapshot_id(after))

    assert diff["comparable"] is True
    assert diff["created"] is None
    assert diff["removed"] is None
    assert diff["completeness"]["complete"] is False
    assert "to:dom_truncated" in diff["completeness"]["reasons"]
    assert diff["field_completeness"] == {
        "created": False,
        "removed": False,
        "changed": False,
    }
    assert {item["id"] for item in diff["changed"]} == {old_submit["id"]}
    hydrated = adapter.hydrate("s1", diff["full_list_ref"])
    assert hydrated["content"]["created"] is None
    assert hydrated["content"]["removed"] is None


def test_snapshot_local_identity_churn_is_not_reported_as_world_create_remove(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    raw = _with_snapshot_local_ax_object()
    before = adapter.snapshot("s1", raw)
    after = adapter.snapshot("s1", raw)

    diff = adapter.diff("s1", _snapshot_id(before), _snapshot_id(after))

    assert diff["comparable"] is True
    assert diff["created"] == []
    assert diff["removed"] == []
    assert diff["changed"] == []
    assert diff["completeness"]["complete"] is False
    assert "identity_unstable_objects" in diff["completeness"]["reasons"]
    assert diff["field_completeness"] == {
        "created": False,
        "removed": False,
        "changed": False,
    }


def test_full_document_generation_change_is_incomparable_not_mass_create_remove(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    after = adapter.snapshot("s1", FIXTURES["navigate"])

    diff = adapter.diff("s1", _snapshot_id(before), _snapshot_id(after))

    assert _bspec_errors(diff, "semantic_diff") == []
    assert diff["comparable"] is False
    assert diff["scope_relation"] == "changed"
    assert diff["created"] is None
    assert diff["removed"] is None
    assert diff["changed"] is None
    assert diff["field_completeness"] == {
        "created": False,
        "removed": False,
        "changed": False,
    }
    assert "scope_changed" in str(diff["reason"])


def test_frame_generation_change_is_incomparable_not_child_mass_churn(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["frame_v1"])
    after = adapter.snapshot("s1", FIXTURES["frame_v2"])

    diff = adapter.diff("s1", _snapshot_id(before), _snapshot_id(after))

    assert diff["comparable"] is False
    assert diff["scope_relation"] == "changed"
    assert diff["created"] is None
    assert diff["removed"] is None
    assert diff["changed"] is None
    assert "frame_scope_changed" in str(diff["reason"])


def test_sensor_contract_change_makes_snapshot_pair_incomparable(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    after = adapter.snapshot("s1", FIXTURES["reorder"])
    after_id = _snapshot_id(after)
    path = adapter.store.root / "snapshots" / f"{after_id}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["snapshot"]["sensor_contract"]["id"] = "browser-dom-ax-test-changed"
    doc["bundle_sha256"] = perception_module._sha256(
        {key: value for key, value in doc.items() if key != "bundle_sha256"}
    )
    path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")

    diff = adapter.diff("s1", _snapshot_id(before), after_id)
    assert diff["comparable"] is False
    assert diff["created"] is None
    assert diff["removed"] is None
    assert diff["changed"] is None
    assert "sensor_contract_changed" in diff["completeness"]["reasons"]


def test_diff_is_session_fenced_and_tool_does_not_need_capture_backend(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    after = adapter.snapshot("s1", FIXTURES["reorder"])
    tool = BrowserPerceiveTool(
        adapter=adapter,
        backend=None,
        session_id_getter=lambda: "s1",
    )

    result = tool.execute(
        action="diff",
        from_version=_snapshot_id(before),
        to_version=_snapshot_id(after),
    )
    assert result.status.value == "success"
    payload = json.loads(result.content)
    assert payload["schema"] == "smc.semantic_diff.v0.1"
    assert payload["comparable"] is True

    other = BrowserPerceiveTool(
        adapter=adapter,
        backend=None,
        session_id_getter=lambda: "s2",
    ).execute(
        action="diff",
        from_version=_snapshot_id(before),
        to_version=_snapshot_id(after),
    )
    assert other.status.value != "success"
    assert "session" in other.content.lower() or "unauthorized" in other.content.lower()


def test_live_semantic_diff_qualification_control_plane_is_not_imported_by_production() -> None:
    marker = "scripts.qualification.smc_browser_live_semantic_diff"
    for path in (ROOT / "src/llm_loop").rglob("*.py"):
        assert marker not in path.read_text(encoding="utf-8")
