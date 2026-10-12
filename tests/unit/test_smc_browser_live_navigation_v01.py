from __future__ import annotations

from pathlib import Path

from scripts.qualification.smc_browser_live_navigation import chrome_args, evaluate_navigation


def _snapshot(*, snapshot_id: str, document_generation: int, object_id: str) -> dict:
    grounding_ref = f"browser-grounding://{snapshot_id}/object/{object_id}"
    return {
        "snapshot": {
            "snapshot_id": snapshot_id,
            "scope": {
                "page_generation": 1,
                "document_generation": document_generation,
            },
        },
        "scope_facts": [
            {
                "kind": "page",
                "scope_ref": "browser-page-scope:stable",
                "page_generation": 1,
                "document_generation": None,
            },
            {
                "kind": "document",
                "scope_ref": f"browser-document-scope:{document_generation}",
                "page_generation": 1,
                "document_generation": document_generation,
            },
        ],
        "objects": [
            {
                "id": object_id,
                "grounding_ref": grounding_ref,
                "observed_version": snapshot_id,
                "attributes": {"name": "Same Name"},
            }
        ],
    }


def test_navigation_evaluator_requires_generation_identity_and_old_grounding() -> None:
    before = _snapshot(snapshot_id="bsnap-before", document_generation=1, object_id="el_old")
    after = _snapshot(snapshot_id="bsnap-after", document_generation=2, object_id="el_new")
    hydrated = {
        "availability": "available",
        "content": {"semantic_object": before["objects"][0]},
    }

    result = evaluate_navigation(
        before,
        after,
        hydrated,
        target_before="target-1",
        target_after="target-1",
        loader_before="loader-1",
        loader_after="loader-2",
    )

    assert result["status"] == "PASS"
    assert all(value == "PASS" for value in result["checks"].values())


def test_navigation_evaluator_rejects_same_generation_identity_reuse() -> None:
    before = _snapshot(snapshot_id="bsnap-before", document_generation=1, object_id="el_same")
    after = _snapshot(snapshot_id="bsnap-after", document_generation=1, object_id="el_same")
    hydrated = {
        "availability": "available",
        "content": {"semantic_object": before["objects"][0]},
    }

    result = evaluate_navigation(
        before,
        after,
        hydrated,
        target_before="target-1",
        target_after="target-1",
        loader_before="loader-1",
        loader_after="loader-2",
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["document_generation_incremented"] == "FAIL"
    assert result["checks"]["same_name_identity_invalidated"] == "FAIL"


def test_qualification_control_plane_is_not_imported_by_production() -> None:
    marker = "scripts.qualification.smc_browser_live_navigation"
    for path in Path("src/llm_loop").rglob("*.py"):
        assert marker not in path.read_text(encoding="utf-8")


def test_qualification_chrome_uses_mock_keychain() -> None:
    args = chrome_args("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", Path("/tmp/profile"), 9222)
    assert "--use-mock-keychain" in args
    assert "--password-store=basic" in args
