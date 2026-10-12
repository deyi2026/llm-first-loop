"""Release workflow ownership regression guard.

The tag-based release workflow is the sole writer of GitHub Release objects.
A second draft writer (Release Drafter) can select an arbitrary existing draft
when several drafts exist and rewrite its name/tag according to NEXT_PATCH_VERSION.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_tag_release_workflow_is_single_release_object_writer() -> None:
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")

    assert "tags:" in release
    assert "'v*'" in release or '"v*"' in release
    assert "softprops/action-gh-release@v2" in release
    assert "draft: true" in release
    assert "generate_release_notes: true" in release

    other_writers: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name == "release.yml":
            continue
        text = path.read_text(encoding="utf-8")
        if "release-drafter/release-drafter" in text or "softprops/action-gh-release" in text:
            other_writers.append(path.name)

    assert other_writers == []


def test_legacy_release_drafter_assets_are_retired() -> None:
    assert not (WORKFLOWS / "release-drafter.yml").exists()
    assert not (ROOT / ".github" / "release-drafter.yml").exists()
