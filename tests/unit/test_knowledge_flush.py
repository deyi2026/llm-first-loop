from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.knowledge_flush import main

CARD = "# 方法卡\n\n适用：示例。\n步骤：一、二、三。\n验证：通过。\n" * 3


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return proc.stdout


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "init")
    return repo


def _write_card(repo: Path, name: str = "method-x") -> Path:
    card_dir = repo / "data" / "methods" / name
    card_dir.mkdir(parents=True, exist_ok=True)
    path = card_dir / "METHOD.md"
    path.write_text(CARD, encoding="utf-8")
    return path


def test_flush_commits_cards_and_experiences(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write_card(repo)
    exp = repo / "experiences"
    exp.mkdir()
    (exp / "EXPERIENCE-1-demo.md").write_text("# 经验\n\n背景与做法。\n" * 3, encoding="utf-8")

    assert main(["--root", str(repo)]) == 0

    subject = _git(repo, "log", "-1", "--pretty=%s").strip()
    assert subject.startswith("knowledge:")
    tracked = _git(repo, "ls-files", "data/methods", "experiences")
    assert "data/methods/method-x/METHOD.md" in tracked
    assert "experiences/EXPERIENCE-1-demo.md" in tracked


def test_flush_is_idempotent(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write_card(repo)
    assert main(["--root", str(repo)]) == 0
    head = _git(repo, "rev-parse", "HEAD").strip()

    assert main(["--root", str(repo)]) == 0
    assert _git(repo, "rev-parse", "HEAD").strip() == head


def test_check_reports_pending_without_committing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write_card(repo)
    head = _git(repo, "rev-parse", "HEAD").strip()

    assert main(["--root", str(repo), "--check"]) == 3
    assert _git(repo, "rev-parse", "HEAD").strip() == head  # 只检查，不提交

    assert main(["--root", str(repo)]) == 0
    assert main(["--root", str(repo), "--check"]) == 0


def test_incomplete_card_dir_is_skipped(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "data" / "methods" / "half").mkdir(parents=True)
    (repo / "data" / "methods" / "half" / "note.txt").write_text("x\n", encoding="utf-8")

    assert main(["--root", str(repo)]) == 0
    assert _git(repo, "log", "-1", "--pretty=%s").strip() == "init"


def test_flush_does_not_sweep_unrelated_staged_changes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write_card(repo)
    (repo / "README.md").write_text("seed changed\n", encoding="utf-8")
    _git(repo, "add", "README.md")

    assert main(["--root", str(repo)]) == 0

    committed = _git(repo, "show", "--name-only", "--pretty=", "HEAD").split()
    assert committed == ["data/methods/method-x/METHOD.md"]
    staged = _git(repo, "diff", "--cached", "--name-only").split()
    assert "README.md" in staged


def test_merge_in_progress_is_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write_card(repo)
    git_dir = repo / _git(repo, "rev-parse", "--git-dir").strip()
    (git_dir / "MERGE_HEAD").write_text("deadbeef\n", encoding="utf-8")

    assert main(["--root", str(repo)]) == 2
    assert _git(repo, "log", "-1", "--pretty=%s").strip() == "init"


def test_flush_commits_card_deletion(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    card = _write_card(repo)
    assert main(["--root", str(repo)]) == 0

    card.unlink()
    assert main(["--root", str(repo)]) == 0

    assert "data/methods/method-x/METHOD.md" not in _git(repo, "ls-files", "data/methods")
