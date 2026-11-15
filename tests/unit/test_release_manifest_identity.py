"""Release manifest must contain upload assets and the immutable tag commit."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "release_finalize_identity_under_test", ROOT / "scripts/release_finalize.py"
)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def test_local_manifest_excludes_build_control_and_body(tmp_path):
    dist = tmp_path / "dist"
    release._make_ci_dist(dist)
    (dist / ".gitignore").write_text("*\n")
    (dist / ".DS_Store").write_text("ignored\n")
    (dist / "release-body-status.md").write_text("not a release asset\n")
    (dist / release.MANIFEST_NAME).write_text("old manifest\n")

    facts = release.collect_local_facts(str(dist))
    assert len(facts) == 7
    assert ".gitignore" not in facts
    assert ".DS_Store" not in facts
    assert "release-body-status.md" not in facts
    assert release.MANIFEST_NAME not in facts
    assert "SHA256SUMS" in facts


def test_sync_uses_peeled_tag_sha_not_moving_main(tmp_path):
    dist = tmp_path / "dist"
    release._make_ci_dist(dist)
    fake = release._draft_fake_from_dist(dist)
    fake.target_commitish = "main"
    fake.tag_commit = "a" * 40

    assert release.sync_manifest_from_release(fake, "v0.6.38") == release.EXIT_OK
    manifest = json.loads(fake.assets[release.MANIFEST_NAME])
    assert manifest["commit_sha"] == "a" * 40
    assert manifest["commit_sha"] != fake.target_commitish
    assert fake.mutations == [("upload", release.MANIFEST_NAME)]


def test_finalize_rejects_manifest_from_moving_branch_without_writes(tmp_path):
    fake = release._green_fake(tmp_path, "drift")
    manifest = json.loads(fake.assets[release.MANIFEST_NAME])
    manifest["commit_sha"] = "main"
    fake.assets[release.MANIFEST_NAME] = release.manifest_bytes(manifest)
    before = list(fake.mutations)

    assert release.finalize_release(fake, "v0.6.38") == release.EXIT_MANIFEST_INVALID
    assert fake.draft is True
    assert fake.mutations == before


def test_gh_resolves_annotated_tag_to_commit_via_api(monkeypatch):
    sha = "7ecc0c4e31c96fd83f5f0643484546dae65df78b"
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=sha + "\n", stderr="")

    monkeypatch.setattr(release.subprocess, "run", fake_run)
    gh = release.GhCli("deyi2026/llm-first-loop")
    assert gh.resolve_tag_commit("v0.6.54") == sha
    assert calls == [["gh", "api", "repos/deyi2026/llm-first-loop/commits/v0.6.54", "--jq", ".sha"]]


def test_tag_resolution_invalid_sha_fails_closed(monkeypatch):
    monkeypatch.setattr(
        release.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="main\n", stderr=""),
    )
    with pytest.raises(release.GhError, match="SHA 无效"):
        release.GhCli("deyi2026/llm-first-loop").resolve_tag_commit("v0.6.54")


def test_finalize_rejects_retargeted_tag_even_with_matching_assets(tmp_path):
    fake = release._green_fake(tmp_path, "retarget")
    fake.tag_commit = "b" * 40  # Simulate tag identity changing after sync.
    before = list(fake.mutations)

    assert release.finalize_release(fake, "v0.6.38") == release.EXIT_MANIFEST_INVALID
    assert fake.draft is True
    assert fake.mutations == before
