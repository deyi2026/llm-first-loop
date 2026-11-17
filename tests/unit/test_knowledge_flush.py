from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.knowledge_flush import _lane_is_stale, main

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
    # 半成品既不入库，也不能留在索引里（否则下一次随手 commit 会被夹带）
    assert _git(repo, "diff", "--cached", "--name-only").strip() == ""


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


# --- lane 相对 worktree 路径的解析基准（回归 2026-11-16） -------------------
# 账本里的 worktree 可能是相对路径（如 ".worktrees/<name>"），它相对**主仓根**。
# linked worktree 内运行时 root 是当前 worktree，旧实现 root/"rel" 必然落到不存在的
# 目录 → 超时且干净的 lane 全被判 live → 知识入库被永久挡住。


def _linked_worktree(repo: Path, name: str = "lane-other") -> Path:
    wt = repo / ".worktrees" / name
    _git(repo, "worktree", "add", "-q", "-b", f"lane/{name}", str(wt))
    return wt


def _lane_row(repo: Path, wt: Path, *, hours_ago: float) -> dict[str, object]:
    ts = datetime.now(UTC) - timedelta(hours=hours_ago)
    return {
        "lane_id": "lane-other",
        "branch": "lane/other",
        "worktree": str(wt.relative_to(repo)),
        "status": "active",
        "last_activity": ts.isoformat(),
        "version": 1,
    }


def test_stale_lane_relative_worktree_resolves_from_main_root(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    wt = _linked_worktree(repo)
    row = _lane_row(repo, wt, hours_ago=6.0)
    now = datetime.now(UTC)

    # 主仓内：基准与 root 一致，行为不变
    assert _lane_is_stale(row, repo, now) is True
    # linked worktree 内：不得解析成 <wt>/.worktrees/lane-other（不存在 → 误判 live）
    assert _lane_is_stale(row, wt, now) is True


def test_live_lane_still_blocks_in_linked_worktree(tmp_path: Path) -> None:
    """修复不放宽闸门：未超时的相对 lane 仍按 live 处理。"""
    repo = _repo(tmp_path)
    wt = _linked_worktree(repo)
    row = _lane_row(repo, wt, hours_ago=1.0)
    now = datetime.now(UTC)

    assert _lane_is_stale(row, repo, now) is False
    assert _lane_is_stale(row, wt, now) is False


def test_flush_in_linked_worktree_not_blocked_by_stale_relative_lane(tmp_path: Path) -> None:
    """端到端：stale 相对 lane 不得挡住 linked worktree 里的知识入库。"""
    repo = _repo(tmp_path)
    other = _linked_worktree(repo, "lane-other")  # 他人 lane：干净但空闲超时
    mine = _linked_worktree(repo, "lane-me")  # 自己运行 flush 的 worktree
    audit = repo / "data" / "audit"
    audit.mkdir(parents=True)
    (audit / "lanes.jsonl").write_text(
        json.dumps(_lane_row(repo, other, hours_ago=6.0)) + "\n", encoding="utf-8"
    )
    _write_card(mine)

    assert main(["--root", str(mine), "--session-id", "sess-me"]) == 0
    assert "data/methods/method-x/METHOD.md" in _git(mine, "ls-files", "data/methods")
