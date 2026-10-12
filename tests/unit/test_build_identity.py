from __future__ import annotations

import subprocess
from pathlib import Path

from llm_loop.runtime.build_identity import compute_build_identity


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def _repo(tmp_path: Path, version: str = "0.6.14") -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"], check=True)
    _git(root, "config", "user.name", "Build Identity Test")
    _git(root, "config", "user.email", "build-identity@example.invalid")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "fixture"\nversion = "{version}"\n', encoding="utf-8"
    )
    (root / "tracked.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    return root


def test_exact_matching_release_tag_is_plain_release(tmp_path: Path) -> None:
    root = _repo(tmp_path, "0.6.14")
    _git(root, "tag", "v0.6.14")

    build = compute_build_identity(root)

    assert build["release_version"] == "0.6.14"
    assert build["expected_release_tag"] == "v0.6.14"
    assert build["nearest_release_tag"] == "v0.6.14"
    assert build["commits_since_release_tag"] == 0
    assert build["release_exact"] is True
    assert build["git_dirty"] is False
    assert build["display"] == "v0.6.14"


def test_post_release_build_uses_git_describe_identity(tmp_path: Path) -> None:
    root = _repo(tmp_path, "0.6.13")
    _git(root, "tag", "v0.6.13")
    (root / "tracked.txt").write_text("two\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", "after release")

    build = compute_build_identity(root)

    assert build["nearest_release_tag"] == "v0.6.13"
    assert build["commits_since_release_tag"] == 1
    assert build["release_exact"] is False
    assert build["display"].startswith("v0.6.13-1-g")


def test_unreleased_next_version_keeps_candidate_version_and_base_tag(tmp_path: Path) -> None:
    root = _repo(tmp_path, "0.6.13")
    _git(root, "tag", "v0.6.13")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.6.14"\n', encoding="utf-8"
    )
    _git(root, "add", "pyproject.toml")
    _git(root, "commit", "-q", "-m", "prepare next version")

    build = compute_build_identity(root)

    assert build["release_version"] == "0.6.14"
    assert build["expected_release_tag"] == "v0.6.14"
    assert build["nearest_release_tag"] == "v0.6.13"
    assert build["commits_since_release_tag"] == 1
    assert build["release_exact"] is False
    assert build["display"].startswith("v0.6.14-dev.1+g")


def test_tracked_dirty_state_is_visible_but_untracked_files_do_not_dirty(tmp_path: Path) -> None:
    root = _repo(tmp_path, "0.6.14")
    _git(root, "tag", "v0.6.14")
    (root / "ignored-runtime.txt").write_text("runtime\n", encoding="utf-8")
    clean = compute_build_identity(root)
    assert clean["git_dirty"] is False
    assert clean["release_exact"] is True

    (root / "tracked.txt").write_text("dirty\n", encoding="utf-8")
    dirty = compute_build_identity(root)
    assert dirty["git_dirty"] is True
    assert dirty["release_exact"] is False
    assert dirty["display"].endswith("-dirty")


def test_no_tag_and_non_git_fallbacks_are_explicitly_unreleased(tmp_path: Path) -> None:
    root = _repo(tmp_path, "0.6.14")
    no_tag = compute_build_identity(root)
    assert no_tag["git_available"] is True
    assert no_tag["nearest_release_tag"] == ""
    assert no_tag["commits_since_release_tag"] is None
    assert no_tag["release_exact"] is False
    assert no_tag["display"].startswith("v0.6.14-dev+g")

    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0.6.14"\n', encoding="utf-8"
    )
    unavailable = compute_build_identity(plain)
    assert unavailable["git_available"] is False
    assert unavailable["git_head"] == ""
    assert unavailable["release_exact"] is False
    assert unavailable["display"] == "v0.6.14-dev+gunknown"
