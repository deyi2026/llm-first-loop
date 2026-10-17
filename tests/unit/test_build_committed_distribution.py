"""The release wheel must come from Git bytes, not a dirty operator checkout."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_committed_distribution.py"
SPEC = importlib.util.spec_from_file_location("committed_distribution", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
distribution = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(distribution)


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


@pytest.fixture
def candidate(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "checkout"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.invalid")
    module = repo / "src" / "llm_loop"
    module.mkdir(parents=True)
    (module / "__init__.py").write_text("VERSION='committed'\n")
    webui = repo / "webui"
    webui.mkdir()
    (webui / "entry.js").write_text("console.log('committed');\n")
    # Ignore node_modules as a symlink too, matching LFL's actual checkout.
    (repo / ".gitignore").write_text("webui/dist/\nwebui/node_modules\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "frozen sources")
    sha = _git(repo, "rev-parse", "HEAD")
    # The operator's untracked module must not enter the package. The
    # modified tracked UI file must not enter the bound UI asset either.
    (module / "event_scan_cache.py").write_text("SECRET_UNCOMMITTED=1\n")
    (webui / "entry.js").write_text("console.log('DIRTY');\n")
    node = tmp_path / "installed-ui-deps"
    (node / ".bin").mkdir(parents=True)
    (node / ".bin" / "vite").write_text("installed-test-binary")
    return repo, node, sha


def _build_fake(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    if command[0] == "npm":
        assert (cwd / "entry.js").read_text() == "console.log('committed');\n"
        assert not (cwd.parent / "src" / "llm_loop" / "event_scan_cache.py").exists()
        dist = cwd / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("from Git snapshot")
        marker = distribution._webui_fingerprint(cwd.parent)
        (dist / ".lfl-webui-source.json").write_text(json.dumps(marker))
    elif command[0] == "uv":
        dest = Path(command[-1])
        dest.mkdir()
        with ZipFile(dest / "llm_first_loop-0.6.32-py3-none-any.whl", "w") as archive:
            archive.writestr("llm_loop/__init__.py", (cwd / "src/llm_loop/__init__.py").read_bytes())
        (dest / "llm_first_loop-0.6.32.tar.gz").write_bytes(b"synthetic-sdist-for-fast-test")
    else:
        raise AssertionError(f"unrecognized build step: {command}")


def test_dirty_checkout_never_enters_committed_wheel(
    candidate: tuple[Path, Path, str], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, node, commit = candidate
    monkeypatch.setattr(distribution, "_run", _build_fake)
    target = tmp_path / "candidate-dist"
    result = distribution.build(repo, "HEAD", target, node)
    assert result["source_commit"] == commit
    assert result["tracked_python_modules"] == 1
    assert result["build_source"] == "detached-clean-git-worktree"
    assert result["publisher_signature_verified"] is False
    with ZipFile(target / "llm_first_loop-0.6.32-py3-none-any.whl") as archive:
        assert archive.namelist() == ["llm_loop/__init__.py"]
        assert b"committed" in archive.read("llm_loop/__init__.py")
    assert json.loads((target / "provenance.json").read_text()) == result
    assert (repo / "src/llm_loop/event_scan_cache.py").exists()
    assert (repo / "webui/entry.js").read_text() == "console.log('DIRTY');\n"
    assert _git(repo, "rev-parse", "HEAD") == commit
    assert "lfl-committed-distribution" not in _git(repo, "worktree", "list")


def test_existing_output_directory_never_overwritten(
    candidate: tuple[Path, Path, str], tmp_path: Path,
) -> None:
    repo, node, _ = candidate
    target = tmp_path / "exists"
    target.mkdir()
    sentinel = target / "operator.txt"
    sentinel.write_bytes(b"keep-my-data")
    with pytest.raises(distribution.CommittedBuildError, match="unused new directory"):
        distribution.build(repo, "HEAD", target, node)
    assert sentinel.read_bytes() == b"keep-my-data"


def test_missing_local_build_deps_fails_before_any_new_worktree(
    candidate: tuple[Path, Path, str], tmp_path: Path,
) -> None:
    repo, _, _ = candidate
    with pytest.raises((FileNotFoundError, distribution.CommittedBuildError)):
        distribution.build(repo, "HEAD", tmp_path / "never-created", tmp_path / "missing")
    assert "lfl-committed-distribution" not in _git(repo, "worktree", "list")


def test_wheel_containing_untracked_extra_python_is_rejected(
    candidate: tuple[Path, Path, str], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, node, _ = candidate

    def unsafe_build(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
        _build_fake(command, cwd=cwd, env=env)
        if command[0] == "uv":
            wheel = next(Path(command[-1]).glob("*.whl"))
            with ZipFile(wheel, "a") as archive:
                archive.writestr("llm_loop/event_scan_cache.py", "untracked input")

    monkeypatch.setattr(distribution, "_run", unsafe_build)
    dest = tmp_path / "cannot-publish"
    with pytest.raises(distribution.CommittedBuildError, match="differ from Git tracked"):
        distribution.build(repo, "HEAD", dest, node)
    assert not dest.exists()
    assert (repo / "src/llm_loop/event_scan_cache.py").exists()


def test_ui_marker_must_match_tracked_sources(
    candidate: tuple[Path, Path, str], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, node, _ = candidate

    def wrong_ui(command: list[str], *, cwd: Path, env: dict[str, str]) -> None:
        _build_fake(command, cwd=cwd, env=env)
        if command[0] == "npm":
            (cwd / "dist" / ".lfl-webui-source.json").write_text('{}')

    monkeypatch.setattr(distribution, "_run", wrong_ui)
    target = tmp_path / "bad-ui"
    with pytest.raises(distribution.CommittedBuildError, match="not bound"):
        distribution.build(repo, "HEAD", target, node)
    assert not target.exists()
