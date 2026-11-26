"""--dev is explicitly denied until trusted Host authorization is implemented.

The negative test uses disposable Git repositories and must never invoke R9
or commit into the actual shared LFL repository.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "dev-lane")
    _git(path, "config", "user.email", "dev@example.invalid")
    _git(path, "config", "user.name", "Dev")
    scripts = path / "scripts"
    scripts.mkdir()
    for name in ("r9_commit.sh", "r9_probe_cleanup.sh"):
        (scripts / name).write_bytes((ROOT / "scripts" / name).read_bytes())
    (path / "seed.txt").write_text("base\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "seed")
    (path / "feature.py").write_text("print('dev')\n")
    _git(path, "add", "feature.py")
    return path


@pytest.mark.parametrize(
    "argv",
    [
        ["--dev", "feat(r9): dev-only"],
        ["feat(r9): dev-only", "--dev"],
        ["--dev=1", "feat(r9): dev-only"],
    ],
)
def test_dev_flag_denied_before_lock_or_index_mutation(repo: Path, argv: list[str]):
    before_head = _git(repo, "rev-parse", "HEAD")
    before_tree = _git(repo, "write-tree")
    env = {
        **os.environ,
        "LFL_R9_DEV_COMMIT_ENABLED": "1",
        "LFL_DEV_HOST_GRANT": "self-asserted-not-valid",
    }
    result = subprocess.run(
        ["bash", "scripts/r9_commit.sh", *argv],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 78
    assert "DEV_COMMIT_DISABLED" in result.stderr
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "write-tree") == before_tree
    assert not (repo / ".git" / "r9-commit.lock").exists()
    assert not list(repo.glob("*.receipt"))


def test_default_commit_path_remains_unchanged(repo: Path):
    result = subprocess.run(
        ["bash", "scripts/r9_commit.sh", "feat(r9): normal"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=15,
    )
    # Disposable repo has no r9_commit_check.sh; it must get past the dev
    # flag guard and fail at the existing check, not silently downgrade.
    assert result.returncode != 0
    assert "DEV_COMMIT_DISABLED" not in result.stderr
    assert _git(repo, "rev-list", "--count", "HEAD") == "1"


@pytest.mark.parametrize("variable", [
    "GIT_DIR", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_CONFIG_COUNT",
    "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
])
def test_normal_r9_rejects_inherited_repo_binding_before_any_write(repo: Path, variable: str):
    foreign = repo.parent / "foreign"
    foreign.mkdir()
    _git(foreign, "init", "-q", "--bare")
    before_config = (foreign / "config").read_bytes()
    before_head = _git(repo, "rev-parse", "HEAD")
    before_tree = _git(repo, "write-tree")
    value = "1" if variable == "GIT_CONFIG_COUNT" else str(foreign)
    if variable in {"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"}:
        override = repo.parent / "foreign.gitconfig"
        _git(repo, "config", "--file", str(override), "core.worktree", str(foreign))
        _git(repo, "config", "--file", str(override), "core.hooksPath", str(foreign / "hooks"))
        value = str(override)
    env = {**os.environ, variable: value}
    result = subprocess.run(
        ["bash", "scripts/r9_commit.sh", "fix: test isolated binding"],
        cwd=repo, env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 78, result.stdout + result.stderr
    assert f"inherited Git repository variable: {variable}" in result.stderr
    assert (foreign / "config").read_bytes() == before_config
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "write-tree") == before_tree
    assert not (repo / ".git" / "r9-commit.lock").exists()
