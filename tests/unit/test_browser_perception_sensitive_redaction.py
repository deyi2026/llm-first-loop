"""FR-6 acceptance tests (DESIGN-20261007-browser-semantic-guard).

Sensitive value_text must be replaced by a sentinel at the sensor layer, so
that canonicalize, persist (snapshot bundles), diff, hydrate, and the
model-facing snapshot projection never see the raw value.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_loop.browser.perception import (
    SENSITIVE_VALUE_SENTINEL,
    BrowserPerceptionAdapter,
    BrowserPerceptionStore,
)

SECRET = "hunter2-super-secret"


def _adapter(tmp_path: Path) -> BrowserPerceptionAdapter:
    store = BrowserPerceptionStore(
        tmp_path / "browser",
        retention_seconds=60,
        now_fn=lambda: 1_000.0,
    )
    return BrowserPerceptionAdapter(store=store, capture_node_cap=10_000)


def _dom_node(
    pid: str,
    name: str,
    *,
    tag: str = "input",
    input_type: str | None = None,
    value: str | None = SECRET,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {"tag": tag, "name": name}
    if input_type:
        attributes["input_type"] = input_type
    if value is not None:
        attributes["value_text"] = value
    return {
        "physical_id": pid,
        "parent_id": None,
        "frame_token": None,
        "kind": "input",
        "attributes": attributes,
        "state": {"exists": True, "enabled": True},
    }


def _ax_node(ax_id: str, name: str, *, value: str = SECRET, role: str = "textField") -> dict[str, Any]:
    attributes: dict[str, Any] = {"role": role, "name": name}
    if value is not None:
        attributes["value_text"] = value
    return {
        "ax_id": ax_id,
        "physical_id": "dom:" + ax_id,
        "frame_token": None,
        "kind": "input",
        "attributes": attributes,
        "state": {"exists": True, "enabled": True},
    }


def _capture(dom_nodes: list, ax_nodes: list) -> dict[str, Any]:
    return {
        "page_token": "page-fr6",
        "document_token": "doc-fr6",
        "url": "https://example.test/fr6",
        "observed_at": "2026-10-07T00:00:00Z",
        "frames": [],
        "dom": {"available": True, "truncated": False, "blind_spots": [], "nodes": dom_nodes},
        "ax": {"available": True, "truncated": False, "blind_spots": [], "nodes": ax_nodes},
    }


def _value_texts(result: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for obj in result["objects"]:
        name = obj["attributes"].get("name")
        if "value_text" in obj["attributes"]:
            out[str(name)] = obj["attributes"]["value_text"]
    return out


def test_dom_password_input_value_is_redacted(tmp_path: Path) -> None:
    capture = _capture(
        [_dom_node("dom:1", "Password", input_type="password")],
        [],
    )
    result = _adapter(tmp_path).snapshot("s1", capture)
    assert _value_texts(result) == {"Password": SENSITIVE_VALUE_SENTINEL}


def test_dom_sensitive_name_redacted_without_input_type(tmp_path: Path) -> None:
    capture = _capture(
        [
            _dom_node("dom:1", "API Token"),
            _dom_node("dom:2", "Verification code"),
            _dom_node("dom:3", "密码"),
        ],
        [],
    )
    result = _adapter(tmp_path).snapshot("s1", capture)
    values = _value_texts(result)
    assert set(values.values()) == {SENSITIVE_VALUE_SENTINEL}


def test_dom_plain_values_are_preserved(tmp_path: Path) -> None:
    capture = _capture(
        [
            _dom_node("dom:1", "Username"),
            _dom_node("dom:2", "Search query"),
        ],
        [],
    )
    result = _adapter(tmp_path).snapshot("s1", capture)
    values = _value_texts(result)
    assert set(values.values()) == {SECRET}


def test_ax_password_and_sensitive_names_are_redacted(tmp_path: Path) -> None:
    capture = _capture(
        [],
        [
            _ax_node("ax:1", "Password"),
            _ax_node("ax:2", "Search query", value="hello world"),
        ],
    )
    result = _adapter(tmp_path).snapshot("s1", capture)
    values = _value_texts(result)
    assert values["Password"] == SENSITIVE_VALUE_SENTINEL
    assert values["Search query"] == "hello world"


def test_persisted_artifacts_contain_no_plaintext_secret(tmp_path: Path) -> None:
    capture = _capture(
        [_dom_node("dom:1", "Password", input_type="password")],
        [_ax_node("ax:1", "Password")],
    )
    adapter = _adapter(tmp_path)
    result = adapter.snapshot("s1", capture)
    # 1) model-facing projection
    assert SECRET not in json.dumps(result)
    assert SENSITIVE_VALUE_SENTINEL in json.dumps(result)
    # 2) everything the store wrote to disk
    written = list((tmp_path / "browser").rglob("*.json"))
    assert written, "expected persisted artifacts"
    for path in written:
        blob = path.read_text(encoding="utf-8")
        assert SECRET not in blob, f"secret leaked into {path}"
    assert any(SENSITIVE_VALUE_SENTINEL in p.read_text(encoding="utf-8") for p in written)


def test_hydrate_returns_sentinel_for_redacted_field(tmp_path: Path) -> None:
    capture = _capture(
        [_dom_node("dom:1", "Password", input_type="password")],
        [],
    )
    adapter = _adapter(tmp_path)
    result = adapter.snapshot("s1", capture)
    obj = next(o for o in result["objects"] if o["attributes"].get("name") == "Password")
    hydrated = adapter.hydrate("s1", obj["grounding_ref"])
    blob = json.dumps(hydrated)
    assert SECRET not in blob
    attributes = hydrated["content"]["semantic_object"]["attributes"]
    assert attributes["value_text"] == SENSITIVE_VALUE_SENTINEL


def test_secret_change_does_not_leak_into_content_sha256(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    capture = _capture([_dom_node("dom:1", "Password", input_type="password", value="old-secret")], [])
    first = adapter.snapshot("s1", capture)
    capture = _capture([_dom_node("dom:1", "Password", input_type="password", value="new-secret")], [])
    second = adapter.snapshot("s1", capture)
    # Bundle-level content hash is identical: the secret never entered the
    # hashed basis, so a changed password produces zero observable delta.
    assert first["snapshot"]["content_sha256"] == second["snapshot"]["content_sha256"]
    diff = adapter.diff("s1", first["snapshot"]["snapshot_id"], second["snapshot"]["snapshot_id"])
    assert diff["changed"] == []
    assert "old-secret" not in json.dumps(diff)
    assert "new-secret" not in json.dumps(diff)


def test_expired_bundle_is_lazily_deleted_with_expired_contract(tmp_path: Path) -> None:
    now = [1_000.0]
    store = BrowserPerceptionStore(
        tmp_path / "browser", retention_seconds=10, now_fn=lambda: now[0]
    )
    adapter = BrowserPerceptionAdapter(store=store)
    result = adapter.snapshot("s1", _capture([_dom_node("dom:1", "Username")], []))
    ref = result["objects"][0]["grounding_ref"]
    assert adapter.hydrate("s1", ref)["availability"] == "available"
    now[0] = 1_011.0
    assert adapter.hydrate("s1", ref)["availability"] == "expired"
    assert list((tmp_path / "browser" / "snapshots").glob("*.json")) == []


def test_overredaction_is_the_accepted_failure_mode(tmp_path: Path) -> None:
    """Known and accepted: substring matching over-redacts benign names.

    e.g. a display field named "token_count" gets the sentinel, which makes
    value assertions on such fields unusable. This is deliberate fail-closed
    behavior (FR-6): over-redaction loses convenience, under-redaction leaks
    secrets. Do not "fix" this by narrowing tokens without fresh leakage
    evidence; extend tokens only on evidence.
    """
    capture = _capture(
        [
            _dom_node("dom:1", "token_count", value="42"),
            _dom_node("dom:2", "Login attempts", value="7"),
        ],
        [],
    )
    result = _adapter(tmp_path).snapshot("s1", capture)
    values = _value_texts(result)
    assert values["token_count"] == SENSITIVE_VALUE_SENTINEL  # over-redacted: accepted
    assert values["Login attempts"] == "7"  # benign fields stay untouched
