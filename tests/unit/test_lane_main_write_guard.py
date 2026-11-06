"""main 直写机械门测试（2026-11-06，并行处理完善建议② / RULE-AI-35）。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from llm_loop.core.lane_main_write_guard import check_git_main_write


def _git_repo(path: Path, branch: str = "main") -> Path:
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "a.txt").write_text("x")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True)
    return path


def _ledger(audit_dir: Path, rows: list[dict]) -> str:
    audit_dir.mkdir(parents=True, exist_ok=True)
    with (audit_dir / "lanes.jsonl").open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return str(audit_dir)


def _lane(lane_id: str, status: str, owner: str, branch: str = "feat/x") -> dict:
    return {
        "lane_id": lane_id,
        "branch": branch,
        "worktree": "/tmp/wt",
        "goal_id": "GOAL-T",
        "owner_session_id": owner,
        "status": status,
        "paths": [],
        "version": 1,
    }


def test_deny_commit_on_main_with_other_active_lane(tmp_path):
    repo = _git_repo(tmp_path / "repo", "main")
    audit = _ledger(tmp_path / "audit", [_lane("lane-a", "active", "sess-other")])
    out = check_git_main_write(
        "git commit -m 'change'", audit_dir=audit, session_id="sess-me", workdir=str(repo)
    )
    assert out is not None
    assert out["reason"] == "lane_main_write_conflict"
    assert "lane-a" in out["detail"]


def test_deny_push_main_with_other_active_lane(tmp_path):
    repo = _git_repo(tmp_path / "repo", "main")
    audit = _ledger(tmp_path / "audit", [_lane("lane-a", "verifying", "sess-other")])
    out = check_git_main_write(
        "git push origin main", audit_dir=audit, session_id="sess-me", workdir=str(repo)
    )
    assert out is not None and out["reason"] == "lane_main_write_conflict"


def test_allow_commit_on_feature_branch(tmp_path):
    repo = _git_repo(tmp_path / "repo", "feat/me")
    audit = _ledger(tmp_path / "audit", [_lane("lane-a", "active", "sess-other")])
    out = check_git_main_write(
        "git commit -m 'change'", audit_dir=audit, session_id="sess-me", workdir=str(repo)
    )
    assert out is None


def test_allow_push_feature_branch(tmp_path):
    repo = _git_repo(tmp_path / "repo", "main")
    audit = _ledger(tmp_path / "audit", [_lane("lane-a", "active", "sess-other")])
    out = check_git_main_write(
        "git push origin feat/x", audit_dir=audit, session_id="sess-me", workdir=str(repo)
    )
    assert out is None


def test_allow_when_only_own_or_closed_lanes(tmp_path):
    repo = _git_repo(tmp_path / "repo", "main")
    audit = _ledger(
        tmp_path / "audit",
        [_lane("lane-me", "active", "sess-me"), _lane("lane-old", "merged", "sess-other")],
    )
    out = check_git_main_write(
        "git commit -m 'change'", audit_dir=audit, session_id="sess-me", workdir=str(repo)
    )
    assert out is None


def test_allow_heredoc_body_not_treated_as_command(tmp_path):
    repo = _git_repo(tmp_path / "repo", "main")
    audit = _ledger(tmp_path / "audit", [_lane("lane-a", "active", "sess-other")])
    cmd = "cat > notes.md <<'EOF'\n记得 git commit 到 main\nEOF"
    out = check_git_main_write(
        cmd, audit_dir=audit, session_id="sess-me", workdir=str(repo)
    )
    assert out is None


def test_allow_when_ledger_missing(tmp_path):
    repo = _git_repo(tmp_path / "repo", "main")
    out = check_git_main_write(
        "git commit -m 'x'",
        audit_dir=str(tmp_path / "nope"),
        session_id="sess-me",
        workdir=str(repo),
    )
    assert out is None


def test_allow_unparseable_branch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    audit = _ledger(tmp_path / "audit", [_lane("lane-a", "active", "sess-other")])
    out = check_git_main_write(
        "git commit -m 'x'", audit_dir=audit, session_id="sess-me", workdir=str(repo)
    )
    assert out is None


def test_tool_gate_denies_commit_on_main_via_wiring(tmp_path, monkeypatch):
    """接线级（RULE-AI-35 实测）：ExecuteCommandTool._lane_main_write_gate 在
    他人 active lane + main 工作树上返回 lane_main_write_denied。"""
    from types import SimpleNamespace

    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool

    repo = _git_repo(tmp_path / "repo", "main")
    audit = _ledger(tmp_path / "audit", [_lane("lane-wire-selftest", "active", "other")])
    monkeypatch.setattr(
        "llm_loop.config.load_settings",
        lambda: SimpleNamespace(audit_dir=Path(audit)),
    )
    tool = ExecuteCommandTool()
    result = tool._lane_main_write_gate("git commit -m x", str(repo))
    assert result is not None
    assert result.error_type == "lane_main_write_denied"


def test_tool_gate_allows_branch_worktree(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool

    repo = _git_repo(tmp_path / "repo", "feat/me")
    monkeypatch.setattr(
        "llm_loop.config.load_settings",
        lambda: SimpleNamespace(audit_dir=tmp_path / "audit"),
    )
    tool = ExecuteCommandTool()
    assert tool._lane_main_write_gate("git commit -m x", str(repo)) is None
