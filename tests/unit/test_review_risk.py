"""Shadow-only risk classification on real Git object ranges."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from llm_loop.tools.review_host_admission import _git
from llm_loop.tools.review_risk import classify_commit_risk


def _run(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _write(repo: Path, name: str, content: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _commit(repo: Path, message: str) -> str:
    _run(repo, "add", "--all")
    _run(repo, "commit", "-qm", message)
    return _run(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    _run(tmp_path, "init", "-q")
    _run(tmp_path, "config", "user.name", "Test")
    _run(tmp_path, "config", "user.email", "test@example.invalid")
    for name in ("README.md", "webui/src/tokens/app.css", "src/llm_loop/llm/pool.py", "src/llm_loop/tools/review_host_admission.py"):
        _write(tmp_path, name, "original\n")
    return tmp_path, _commit(tmp_path, "base")


@pytest.mark.parametrize(("path", "content", "tier"), [
    ("README.md", "new documentation\n", "low"),
    ("webui/src/tokens/app.css", "margin: 8px;\n", "medium"),
    ("src/llm_loop/llm/pool.py", "retry_count = 2\n", "medium"),
    ("src/llm_loop/llm/pool.py", "api_key = None\n", "high"),
    ("webui/src/tokens/app.css", "display: none;\n", "high"),
    ("src/llm_loop/tools/review_host_admission.py", "changed\n", "high"),
    ("unknown.py", "new\n", "high"),
])
def test_risk_on_real_commits(repo, path, content, tier):
    root, base = repo
    _write(root, path, content)
    candidate = _commit(root, "candidate")
    result = classify_commit_risk(_git, root, base, candidate)
    assert result["tier"] == tier, result
    assert result["base_sha"] == base and result["candidate_sha"] == candidate
    assert result["mode"] == "shadow_only" and result["review_required"] is True
    assert result["release_qualified"] is False


def test_reverted_protected_change_still_high(repo):
    root, base = repo
    protected = "src/llm_loop/tools/review_host_admission.py"
    _write(root, protected, "changed\n")
    _commit(root, "temporary change")
    _write(root, protected, "original\n")
    _write(root, "README.md", "new documentation\n")
    head = _commit(root, "restore")
    assert classify_commit_risk(_git, root, base, head)["tier"] == "high"


def test_untrusted_ref_or_missing_objects_fail_closed(repo):
    root, base = repo
    assert classify_commit_risk(_git, root, "HEAD", base)["tier"] == "high"
    assert classify_commit_risk(_git, root, "a" * 40, base)["tier"] == "high"
    assert classify_commit_risk(_git, root, base, base)["tier"] == "high"


def test_symlink_and_mode_change_high(repo):
    root, base = repo
    p = root / "README.md"
    p.unlink()
    p.symlink_to("webui/src/tokens/app.css")
    head = _commit(root, "symlink")
    assert classify_commit_risk(_git, root, base, head)["tier"] == "high"


def test_intermediate_mode_change_is_high(repo):
    root, base = repo
    p = root / "README.md"
    p.chmod(0o755)
    _commit(root, "executable")
    p.chmod(0o644)
    p.write_text("new documentation\n")
    head = _commit(root, "restore mode")
    assert classify_commit_risk(_git, root, base, head)["tier"] == "high"
