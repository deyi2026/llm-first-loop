from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from llm_loop.browser.perception import BrowserPerceptionAdapter, BrowserPerceptionStore

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = json.loads(
    (ROOT / "tests/fixtures/smc_browser_perception_v01.json").read_text(encoding="utf-8")
)


def _adapter(
    tmp_path: Path,
    *,
    now: list[float] | None = None,
    retention_seconds: int = 60,
) -> BrowserPerceptionAdapter:
    clock = now if now is not None else [1_000.0]
    return BrowserPerceptionAdapter(
        store=BrowserPerceptionStore(
            tmp_path / "browser",
            retention_seconds=retention_seconds,
            now_fn=lambda: clock[0],
        ),
        capture_node_cap=10_000,
    )


def _sid(snapshot: dict[str, Any]) -> str:
    return str(snapshot["snapshot"]["snapshot_id"])


def _page_scope(snapshot: dict[str, Any]) -> str:
    return str(next(s for s in snapshot["scope_facts"] if s["kind"] == "page")["scope_ref"])


def _document_scope(snapshot: dict[str, Any]) -> str:
    return str(snapshot["snapshot"]["scope"]["scope_ref"])


def _dom_named(snapshot: dict[str, Any], name: str) -> dict[str, Any]:
    matches = [
        obj
        for obj in snapshot["objects"]
        if obj["attributes"].get("name") == name
        and "dom" in obj.get("coverage", {}).get("sources", [])
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one DOM-backed {name!r}, got {len(matches)}")
    return matches[0]


def _assert_common_shape(result: dict[str, Any]) -> None:
    assert set(result) == {
        "schema",
        "domain",
        "version_scope",
        "scope_ref",
        "target_id",
        "expected_version",
        "observed_version",
        "expected_availability",
        "observed_availability",
        "result",
        "reason",
        "comparable",
        "pressure",
        "automatic_refresh_performed",
        "silent_rebind_performed",
    }
    assert result["schema"] == "smc.browser_version_assessment.v0.1"
    assert result["domain"] == "browser"
    assert result["automatic_refresh_performed"] is False
    assert result["silent_rebind_performed"] is False
    assert set(result["pressure"]) == {
        "present",
        "expected_expires_at_epoch",
        "observed_expires_at_epoch",
        "expected_seconds_until_expiry",
        "observed_seconds_until_expiry",
    }


def test_exact_snapshot_version_matches_without_refresh(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    snap = adapter.snapshot("s1", FIXTURES["base"])
    sid = _sid(snap)

    result = adapter.assess_version_precondition(
        "s1",
        expected_version=sid,
        observed_version=sid,
        version_scope="snapshot",
        scope_ref=_document_scope(snap),
    )

    _assert_common_shape(result)
    assert result["result"] == "match"
    assert result["reason"] == "exact_version"
    assert result["comparable"] is True
    assert result["pressure"]["present"] is False
    assert result["expected_availability"] == "available"
    assert result["observed_availability"] == "available"


def test_object_scope_ignores_unrelated_same_document_change_but_pressure_is_visible(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    after = adapter.snapshot("s1", FIXTURES["reorder"])
    old_submit = _dom_named(before, "Submit")
    new_submit = _dom_named(after, "Submit")
    assert old_submit["id"] == new_submit["id"]

    result = adapter.assess_version_precondition(
        "s1",
        expected_version=_sid(before),
        observed_version=_sid(after),
        version_scope="object",
        scope_ref=str(old_submit["scope_ref"]),
        target_id=str(old_submit["id"]),
    )

    _assert_common_shape(result)
    assert result["result"] == "match"
    assert result["reason"] == "object_unchanged_new_observation"
    assert result["comparable"] is True
    assert result["pressure"]["present"] is True
    assert adapter.hydrate("s1", str(old_submit["grounding_ref"]))["availability"] == "available"
    assert adapter.diff("s1", _sid(before), _sid(after))["comparable"] is True


def test_object_scope_detects_target_change_same_generation(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    changed = deepcopy(FIXTURES["base"])
    for source in ("dom", "ax"):
        for node in changed[source]["nodes"]:
            if node.get("physical_id") == "n-submit":
                node.setdefault("state", {})["enabled"] = False
    after = adapter.snapshot("s1", changed)
    old_submit = _dom_named(before, "Submit")

    result = adapter.assess_version_precondition(
        "s1",
        expected_version=_sid(before),
        observed_version=_sid(after),
        version_scope="object",
        scope_ref=str(old_submit["scope_ref"]),
        target_id=str(old_submit["id"]),
    )

    _assert_common_shape(result)
    assert result["result"] == "stale"
    assert result["reason"] == "object_changed_same_generation"
    assert result["comparable"] is True
    assert result["pressure"]["present"] is True


def test_snapshot_scope_treats_distinct_observation_as_stale(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    after = adapter.snapshot("s1", FIXTURES["base"])

    result = adapter.assess_version_precondition(
        "s1",
        expected_version=_sid(before),
        observed_version=_sid(after),
        version_scope="snapshot",
        scope_ref=_document_scope(before),
    )

    _assert_common_shape(result)
    assert result["result"] == "stale"
    assert result["reason"] == "different_snapshot_same_generation"
    assert result["pressure"]["present"] is True


def test_resource_scope_uses_document_resource_facts(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    unchanged = adapter.snapshot("s1", FIXTURES["base"])
    changed = adapter.snapshot("s1", FIXTURES["push_state"])

    same = adapter.assess_version_precondition(
        "s1",
        expected_version=_sid(before),
        observed_version=_sid(unchanged),
        version_scope="resource",
        scope_ref=_page_scope(before),
    )
    moved = adapter.assess_version_precondition(
        "s1",
        expected_version=_sid(before),
        observed_version=_sid(changed),
        version_scope="resource",
        scope_ref=_page_scope(before),
    )

    assert same["result"] == "match"
    assert same["reason"] == "resource_unchanged_new_observation"
    assert same["pressure"]["present"] is True
    assert moved["result"] == "stale"
    assert moved["reason"] == "resource_changed_same_generation"
    assert moved["comparable"] is True


def test_document_generation_change_is_stale_not_same_name_rebind(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    after = adapter.snapshot("s1", FIXTURES["navigate"])
    old_submit = _dom_named(before, "Submit")
    new_submit = _dom_named(after, "Submit")
    assert old_submit["id"] != new_submit["id"]

    result = adapter.assess_version_precondition(
        "s1",
        expected_version=_sid(before),
        observed_version=_sid(after),
        version_scope="object",
        scope_ref=str(old_submit["scope_ref"]),
        target_id=str(old_submit["id"]),
    )

    _assert_common_shape(result)
    assert result["result"] == "stale"
    assert result["reason"] == "document_generation_changed"
    assert result["comparable"] is False
    assert result["target_id"] == old_submit["id"]
    assert result["silent_rebind_performed"] is False


def test_resource_scope_detects_document_generation_pressure_on_same_page(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    after = adapter.snapshot("s1", FIXTURES["navigate"])
    assert _page_scope(before) == _page_scope(after)

    result = adapter.assess_version_precondition(
        "s1",
        expected_version=_sid(before),
        observed_version=_sid(after),
        version_scope="resource",
        scope_ref=_page_scope(before),
    )

    _assert_common_shape(result)
    assert result["result"] == "stale"
    assert result["reason"] == "document_generation_changed"
    assert result["comparable"] is False
    assert result["pressure"]["present"] is True


def test_incomplete_observation_does_not_turn_missing_target_into_stale(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    old_submit = _dom_named(before, "Submit")
    raw = deepcopy(FIXTURES["base"])
    for sensor in ("dom", "ax"):
        raw[sensor]["nodes"] = [
            node for node in raw[sensor]["nodes"] if node.get("physical_id") != "n-submit"
        ]
    raw["dom"]["truncated"] = True
    after = adapter.snapshot("s1", raw)
    assert after["snapshot"]["completeness"]["complete"] is False

    result = adapter.assess_version_precondition(
        "s1",
        expected_version=_sid(before),
        observed_version=_sid(after),
        version_scope="object",
        scope_ref=str(old_submit["scope_ref"]),
        target_id=str(old_submit["id"]),
    )

    _assert_common_shape(result)
    assert result["result"] == "indeterminate"
    assert result["reason"] == "target_not_observed_incomplete"
    assert result["comparable"] is True


def test_expired_expected_version_is_indeterminate_not_silently_refreshed(tmp_path: Path) -> None:
    now = [1_000.0]
    adapter = _adapter(tmp_path, now=now, retention_seconds=10)
    before = adapter.snapshot("s1", FIXTURES["base"])
    now[0] = 1_005.0
    after = adapter.snapshot("s1", FIXTURES["push_state"])
    now[0] = 1_011.0

    result = adapter.assess_version_precondition(
        "s1",
        expected_version=_sid(before),
        observed_version=_sid(after),
        version_scope="snapshot",
        scope_ref=_document_scope(before),
    )

    _assert_common_shape(result)
    assert result["result"] == "indeterminate"
    assert result["reason"] == "expected_version_expired"
    assert result["expected_availability"] == "expired"
    assert result["observed_availability"] == "available"
    assert result["pressure"]["expected_seconds_until_expiry"] == 0.0


def test_unknown_or_unauthorized_versions_are_indeterminate(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    snap = adapter.snapshot("s1", FIXTURES["base"])

    missing = adapter.assess_version_precondition(
        "s1",
        expected_version="bsnap-1-deadbeefdeadbeef",
        observed_version=_sid(snap),
        version_scope="snapshot",
        scope_ref=_document_scope(snap),
    )
    assert missing["result"] == "indeterminate"
    assert missing["reason"] == "expected_version_unavailable"

    unauthorized = adapter.assess_version_precondition(
        "other-session",
        expected_version=_sid(snap),
        observed_version=_sid(snap),
        version_scope="snapshot",
        scope_ref=_document_scope(snap),
    )
    assert unauthorized["result"] == "indeterminate"
    assert unauthorized["reason"] == "expected_version_unauthorized"


def test_evicted_backing_snapshot_is_unavailable_not_refetched(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    before = adapter.snapshot("s1", FIXTURES["base"])
    after = adapter.snapshot("s1", FIXTURES["push_state"])
    old_ref = str(_dom_named(before, "Submit")["grounding_ref"])
    adapter.store._bundle_path(_sid(before)).unlink()

    result = adapter.assess_version_precondition(
        "s1",
        expected_version=_sid(before),
        observed_version=_sid(after),
        version_scope="snapshot",
        scope_ref=_document_scope(before),
    )

    _assert_common_shape(result)
    assert result["result"] == "indeterminate"
    assert result["reason"] == "expected_version_unavailable"
    assert adapter.hydrate("s1", old_ref)["availability"] == "unavailable"
    assert result["automatic_refresh_performed"] is False


def test_snapshot_local_identity_cannot_be_version_guard_target(tmp_path: Path) -> None:
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
    adapter = _adapter(tmp_path)
    snap = adapter.snapshot("s1", raw)
    local = next(obj for obj in snap["objects"] if obj["attributes"].get("name") == "Local only")

    result = adapter.assess_version_precondition(
        "s1",
        expected_version=_sid(snap),
        observed_version=_sid(snap),
        version_scope="object",
        scope_ref=str(local["scope_ref"]),
        target_id=str(local["id"]),
    )

    _assert_common_shape(result)
    assert result["result"] == "indeterminate"
    assert result["reason"] == "target_identity_unstable"


def test_invalid_version_scope_is_rejected_not_coerced(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    snap = adapter.snapshot("s1", FIXTURES["base"])

    try:
        adapter.assess_version_precondition(
            "s1",
            expected_version=_sid(snap),
            observed_version=_sid(snap),
            version_scope="document",
            scope_ref=_document_scope(snap),
        )
    except ValueError as exc:
        assert "version_scope" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("invalid version_scope must be rejected")


def test_version_assessment_does_not_expand_model_surface(tmp_path: Path) -> None:
    from llm_loop.tools.builtin.browser_perceive import BrowserPerceiveTool

    tool = BrowserPerceiveTool(
        adapter=_adapter(tmp_path),
        backend=None,
        session_id_getter=lambda: "s1",
    )
    props = tool.parameters["properties"]
    assert props["action"]["enum"] == ["snapshot", "hydrate", "diff", "wait"]
    assert "expected_version" not in props
    assert "observed_version" not in props
    assert "version_scope" not in props
    assert "version_status" not in props["action"]["enum"]
