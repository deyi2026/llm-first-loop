"""Mechanical release/build identity for local and deployed LFL runtimes.

Release version and development build identity are deliberately separate:
- ``release_version`` comes from the workspace ``pyproject.toml``.
- Git facts describe the exact bytes lineage at process start.
- ``release_exact`` is true only when HEAD carries the matching ``v<version>``
  tag and tracked files are clean.

No field in this module selects features, providers, models, or task policy.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path
from typing import Any

_GIT_TIMEOUT_S = 5


def _release_version(workspace: Path) -> str:
    try:
        with (workspace / "pyproject.toml").open("rb") as handle:
            value = tomllib.load(handle).get("project", {}).get("version", "")
    except (OSError, tomllib.TOMLDecodeError, AttributeError):
        return ""
    return str(value or "").strip()


def _git(workspace: Path, *args: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(workspace), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    if proc.returncode != 0:
        return False, ""
    return True, proc.stdout.strip()


def compute_build_identity(workspace_root: str | Path) -> dict[str, Any]:
    """Return prompt-neutral release/build facts for ``workspace_root``.

    Untracked/ignored runtime files do not make a build dirty.  This is
    intentional: the identity is for tracked source bytes, while runtime data
    already has separate manifest/config hashes.
    """

    workspace = Path(workspace_root).expanduser().resolve()
    release_version = _release_version(workspace)
    expected_release_tag = f"v{release_version}" if release_version else ""

    head_ok, git_head = _git(workspace, "rev-parse", "HEAD")
    if not head_ok:
        display = (
            f"v{release_version}-dev+gunknown" if release_version else "unversioned-dev+gunknown"
        )
        return {
            "release_version": release_version,
            "expected_release_tag": expected_release_tag,
            "nearest_release_tag": "",
            "commits_since_release_tag": None,
            "git_available": False,
            "git_head": "",
            "git_short": "",
            "git_dirty": False,
            "release_exact": False,
            "git_describe": "",
            "display": display,
        }

    git_short = git_head[:8]
    _, dirty_text = _git(workspace, "status", "--porcelain", "--untracked-files=no")
    git_dirty = bool(dirty_text.strip())

    tag_ok, nearest_release_tag = _git(
        workspace, "describe", "--tags", "--match", "v[0-9]*", "--abbrev=0"
    )
    if not tag_ok:
        nearest_release_tag = ""

    commits_since_release_tag: int | None = None
    if nearest_release_tag:
        count_ok, count_text = _git(
            workspace, "rev-list", "--count", f"{nearest_release_tag}..HEAD"
        )
        if count_ok:
            try:
                commits_since_release_tag = int(count_text)
            except ValueError:
                commits_since_release_tag = None

    tags_ok, tags_text = _git(workspace, "tag", "--points-at", "HEAD")
    head_tags = set(tags_text.splitlines()) if tags_ok and tags_text else set()
    matching_tag_at_head = bool(expected_release_tag and expected_release_tag in head_tags)
    release_exact = matching_tag_at_head and not git_dirty

    describe_ok, git_describe = _git(
        workspace, "describe", "--tags", "--match", "v[0-9]*", "--long", "--always"
    )
    if not describe_ok:
        git_describe = f"g{git_short}"
    if git_dirty:
        git_describe = f"{git_describe}-dirty"

    nearest_version = nearest_release_tag.removeprefix("v") if nearest_release_tag else ""
    if release_exact:
        display = expected_release_tag
    elif release_version and nearest_release_tag and release_version == nearest_version:
        display = git_describe
    elif release_version and commits_since_release_tag is not None:
        display = f"v{release_version}-dev.{commits_since_release_tag}+g{git_short}"
        if git_dirty:
            display += ".dirty"
    elif release_version:
        display = f"v{release_version}-dev+g{git_short}"
        if git_dirty:
            display += ".dirty"
    else:
        display = git_describe or f"unversioned-dev+g{git_short}"

    return {
        "release_version": release_version,
        "expected_release_tag": expected_release_tag,
        "nearest_release_tag": nearest_release_tag,
        "commits_since_release_tag": commits_since_release_tag,
        "git_available": True,
        "git_head": git_head,
        "git_short": git_short,
        "git_dirty": git_dirty,
        "release_exact": release_exact,
        "git_describe": git_describe,
        "display": display,
    }
