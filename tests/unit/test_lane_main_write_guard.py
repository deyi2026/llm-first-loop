"""main 直写机械门测试（2026-11-06，并行处理完善建议② / RULE-AI-35）。"""
from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from llm_loop.core import lane_main_write_guard as guard_module
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


def test_deny_push_with_merging_lane(tmp_path):
    """P2-3：merging 是收口动作，同样挡 push，且 reason_code 可区分。"""
    repo = _git_repo(tmp_path / "repo", "main")
    audit = _ledger(tmp_path / "audit", [_lane("lane-m", "merging", "sess-other")])
    out = check_git_main_write(
        "git push origin main", audit_dir=audit, session_id="sess-me", workdir=str(repo)
    )
    assert out is not None
    assert out["reason_code"] == "main_push_closing_lane"


def test_push_refspec_variants_to_main_detected(tmp_path):
    """P2（R5）：`+main`、`refs/heads/main`、`HEAD:main` 都要被识别，否则可绕过收口拦截。"""
    repo = _git_repo(tmp_path / "repo", "main")
    audit = _ledger(tmp_path / "audit", [_lane("lane-m", "verifying", "sess-other")])
    for cmd in (
        "git push origin +main",
        "git push origin refs/heads/main",
        "git push origin HEAD:main",
    ):
        out = check_git_main_write(
            cmd, audit_dir=audit, session_id="me", workdir=str(repo)
        )
        assert out is not None and out["reason_code"] == "main_push_closing_lane", cmd
    # 非 main 的完全限定名不得误判
    ok = check_git_main_write(
        "git push origin refs/heads/feat/x",
        audit_dir=audit,
        session_id="me",
        workdir=str(repo),
    )
    assert ok is None


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


# --- review P2#1 覆盖补强：push 无 refspec / --all / --mirror ---


def test_push_remote_only_allows_open_active_lane(tmp_path):
    """EVO-20261109：open/active 只挡 commit，不挡 push；verifying/merging 才挡。"""
    repo = _git_repo(tmp_path / "r")
    audit = _ledger(tmp_path / "a", [_lane("l1", "active", "other-sess")])
    verdict = check_git_main_write(
        "git push origin", audit_dir=audit, session_id="me", workdir=str(repo)
    )
    assert verdict is None


def test_push_all_denied_with_other_lane(tmp_path):
    repo = _git_repo(tmp_path / "r")
    audit = _ledger(tmp_path / "a", [_lane("l1", "active", "other-sess")])
    verdict = check_git_main_write(
        "git push --all", audit_dir=audit, session_id="me", workdir=str(repo)
    )
    assert verdict is not None


def test_push_mirror_denied_with_other_lane(tmp_path):
    repo = _git_repo(tmp_path / "r")
    audit = _ledger(tmp_path / "a", [_lane("l1", "merging", "other-sess")])
    verdict = check_git_main_write(
        "git push origin --mirror", audit_dir=audit, session_id="me", workdir=str(repo)
    )
    assert verdict is not None


def test_push_feature_branch_allowed(tmp_path):
    repo = _git_repo(tmp_path / "r")
    audit = _ledger(tmp_path / "a", [_lane("l1", "active", "other-sess")])
    assert (
        check_git_main_write(
            "git push origin feat/x", audit_dir=audit, session_id="me", workdir=str(repo)
        )
        is None
    )


# --- EVO-20261109-0e5fdde5：失效回收 + push 判据拆分（RULE-AI-35 双向实测） ---


def _iso_ago(hours: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


def _clean_worktree(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def _stale(lane_id: str, worktree: str, **extra) -> dict:
    row = {
        **_lane(lane_id, "verifying", "sess-other"),
        "worktree": worktree,
        "last_activity": _iso_ago(10),
    }
    row.update(extra)
    return row


def test_stale_lane_clean_worktree_reclaimed_and_annotated(tmp_path):
    """闲置 >TTL 且 worktree 无未提交改动 → 不再计入 blocker，回执标注依据。"""
    repo = _git_repo(tmp_path / "repo", "main")
    wt = _clean_worktree(tmp_path / "wt")
    live = {
        **_lane("lane-live", "verifying", "sess-other2", branch="feat/y"),
        "last_activity": _iso_ago(0.1),
    }
    audit = _ledger(tmp_path / "audit", [_stale("lane-old", str(wt)), live])
    out = check_git_main_write(
        "git push origin main", audit_dir=audit, session_id="sess-me", workdir=str(repo)
    )
    assert out is not None  # live verifying 仍挡
    assert [row["lane_id"] for row in out["stale_lanes"]] == ["lane-old"]
    assert out["stale_lanes"][0]["reclaim_basis"] == "clean_worktree"
    assert "已按失效回收忽略" in out["detail"]
    assert "lane-old" not in out["detail"].split("已按失效回收忽略")[0]


def test_stale_lane_dirty_worktree_still_blocks(tmp_path):
    repo = _git_repo(tmp_path / "repo", "main")
    wt = _clean_worktree(tmp_path / "wt")
    (wt / "uncommitted.txt").write_text("x")
    audit = _ledger(tmp_path / "audit", [_stale("lane-old", str(wt))])
    out = check_git_main_write(
        "git commit -m x", audit_dir=audit, session_id="sess-me", workdir=str(repo)
    )
    assert out is not None
    assert out["stale_lanes"] == []


def test_stale_lane_merged_head_reclaimed(tmp_path):
    repo = _git_repo(tmp_path / "repo", "main")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    audit = _ledger(
        tmp_path / "audit", [_stale("lane-merged", "/nonexistent/wt", head_sha=head)]
    )
    assert (
        check_git_main_write(
            "git commit -m x", audit_dir=audit, session_id="sess-me", workdir=str(repo)
        )
        is None
    )


def test_stale_lane_unverifiable_still_blocks(tmp_path):
    """闲置够久但既未合并、worktree 也不可判定 → 保守按 live（fail-closed）。"""
    repo = _git_repo(tmp_path / "repo", "main")
    audit = _ledger(
        tmp_path / "audit",
        [_stale("lane-unknown", "/nonexistent/wt", head_sha="0" * 40)],
    )
    assert (
        check_git_main_write(
            "git commit -m x", audit_dir=audit, session_id="sess-me", workdir=str(repo)
        )
        is not None
    )


def test_fresh_lane_never_reclaimed(tmp_path):
    repo = _git_repo(tmp_path / "repo", "main")
    wt = _clean_worktree(tmp_path / "wt")
    row = _stale("lane-fresh", str(wt))
    row["last_activity"] = _iso_ago(0.5)
    audit = _ledger(tmp_path / "audit", [row])
    assert (
        check_git_main_write(
            "git commit -m x", audit_dir=audit, session_id="sess-me", workdir=str(repo)
        )
        is not None
    )


def test_relative_lane_worktree_resolves_against_main_repo(tmp_path):
    """相对 worktree 路径以主仓库根为基准——命令在子 worktree 执行也判得准。"""
    repo = _git_repo(tmp_path / "repo", "main")
    other = repo / ".worktrees" / "wt-other"
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "worktree",
            "add",
            "-q",
            str(other),
            "-b",
            "feat/other",
        ],
        check=True,
    )
    audit = _ledger(tmp_path / "audit", [_stale("lane-old", ".worktrees/wt-other")])
    verdict = check_git_main_write(
        "git push origin main", audit_dir=audit, session_id="me", workdir=str(other)
    )
    assert verdict is None


def _bare_remote(tmp_path: Path, repo: Path) -> Path:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(bare)], check=True)
    return bare


def test_push_non_fast_forward_denied(tmp_path):
    repo = _git_repo(tmp_path / "repo", "main")
    bare = _bare_remote(tmp_path, repo)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "t"], check=True)
    (clone / "b.txt").write_text("y")
    subprocess.run(["git", "-C", str(clone), "add", "."], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "ahead"], check=True)
    subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "main"], check=True)
    audit = _ledger(tmp_path / "audit", [_lane("l1", "active", "other")])
    out = check_git_main_write(
        f"git push {bare} main", audit_dir=audit, session_id="me", workdir=str(repo)
    )
    assert out is not None
    assert out["reason_code"] == "main_push_not_fast_forward"


def test_push_fast_forward_allowed(tmp_path):
    repo = _git_repo(tmp_path / "repo", "main")
    bare = _bare_remote(tmp_path, repo)
    (repo / "b.txt").write_text("y")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "local-ahead"], check=True)
    audit = _ledger(tmp_path / "audit", [_lane("l1", "active", "other")])
    assert (
        check_git_main_write(
            f"git push {bare} main", audit_dir=audit, session_id="me", workdir=str(repo)
        )
        is None
    )


def test_push_unreachable_remote_fail_open(tmp_path):
    repo = _git_repo(tmp_path / "repo", "main")
    audit = _ledger(tmp_path / "audit", [_lane("l1", "active", "other")])
    assert (
        check_git_main_write(
            "git push no-such-remote-xyz main",
            audit_dir=audit,
            session_id="me",
            workdir=str(repo),
        )
        is None
    )


def test_git_dash_c_commit_uses_target_repo_branch(tmp_path):
    """从 feature worktree 用 `git -C <main>` 提交，也必须按 main 判定（防改道）。"""
    main = _git_repo(tmp_path / "main", "main")
    feat = tmp_path / "feat"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-q", "-b", "feat/x", str(feat)],
        check=True,
    )
    audit = _ledger(tmp_path / "audit", [_lane("l1", "open", "other")])
    out = check_git_main_write(
        f"git -C {main} commit -m x",
        audit_dir=audit,
        session_id="me",
        workdir=str(feat),
    )
    assert out is not None and out["operation"] == "commit"


def test_git_dash_c_feature_branch_still_allowed(tmp_path):
    """`git -C <feature worktree>` 提交不误伤（判定跟随 -C，而非命令 workdir）。"""
    main = _git_repo(tmp_path / "main", "main")
    feat = tmp_path / "feat"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-q", "-b", "feat/x", str(feat)],
        check=True,
    )
    audit = _ledger(tmp_path / "audit", [_lane("l1", "open", "other")])
    assert (
        check_git_main_write(
            f"git -C {feat} commit -m x",
            audit_dir=audit,
            session_id="me",
            workdir=str(main),
        )
        is None
    )


def test_git_dash_c_chained_relative_segment(tmp_path):
    """P1（R4）：`git -C A -C repo` 后段相对前段链式解析，不得只看最后一段。"""
    host = tmp_path / "host"
    host.mkdir(parents=True, exist_ok=True)
    _git_repo(host / "repo", "main")
    other = _git_repo(tmp_path / "other", "main")
    subprocess.run(
        ["git", "-C", str(other), "checkout", "-q", "-b", "feat/x"], check=True
    )
    audit = _ledger(tmp_path / "audit", [_lane("l1", "open", "other")])
    out = check_git_main_write(
        f"git -C {host} -C repo commit -m x",
        audit_dir=audit,
        session_id="me",
        workdir=str(other),
    )
    assert out is not None and out["reason_code"] == "main_commit_other_lane"


# --- 审查 R2/R4（P1）回归：push 跟随 -C、-C 链式解析、浅克隆不误拒 ---


def test_git_dash_c_push_non_ff_checked_on_target_repo(tmp_path):
    """P1-1：`git -C <main> push` 的快进校验必须基于 -C 目标仓库。"""
    repo = _git_repo(tmp_path / "repo", "main")
    bare = _bare_remote(tmp_path, repo)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "t"], check=True)
    (clone / "b.txt").write_text("y")
    subprocess.run(["git", "-C", str(clone), "add", "."], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "ahead"], check=True)
    subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "main"], check=True)
    audit = _ledger(tmp_path / "audit", [_lane("l1", "active", "other")])
    # ambient workdir 必须是**独立对象库**的 clone：linked worktree 与 repo 共享
    # 对象库，旧实现（用 ambient workdir）也会判非快进，测试将失去判别力。
    out = check_git_main_write(
        f"git -C {repo} push {bare} main",
        audit_dir=audit,
        session_id="me",
        workdir=str(clone),
    )
    assert out is not None and "非快进" in out.get("detail", "")


def test_shallow_clone_missing_object_not_denied(tmp_path):
    """P1-2：浅克隆里远端对象本地缺失不能证明非快进 → 放行（无法判定）。"""
    repo = _git_repo(tmp_path / "repo", "main")
    bare = _bare_remote(tmp_path, repo)
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{bare}", str(shallow)],
        check=True,
    )
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(clone), "config", "user.name", "t"], check=True)
    (clone / "c.txt").write_text("z")
    subprocess.run(["git", "-C", str(clone), "add", "."], check=True)
    subprocess.run(["git", "-C", str(clone), "commit", "-qm", "ahead2"], check=True)
    subprocess.run(["git", "-C", str(clone), "push", "-q", "origin", "main"], check=True)
    audit = _ledger(tmp_path / "audit", [_lane("l1", "active", "other")])
    assert (
        check_git_main_write(
            f"git push {bare} main",
            audit_dir=audit,
            session_id="me",
            workdir=str(shallow),
        )
        is None
    )


def test_stale_reclaim_disabled_when_ttl_non_positive(tmp_path, monkeypatch):
    """TTL<=0 关闭回收：旧的干净 lane 仍然挡（保守闩）。"""
    monkeypatch.setattr(guard_module, "STALE_AFTER_S", 0)
    repo = _git_repo(tmp_path / "repo", "main")
    wt = _clean_worktree(tmp_path / "wt")
    audit = _ledger(tmp_path / "audit", [_stale("lane-old", str(wt))])
    assert (
        check_git_main_write(
            "git commit -m x", audit_dir=audit, session_id="me", workdir=str(repo)
        )
        is not None
    )


def test_stale_lane_created_at_fallback(tmp_path):
    """P2-4：缺 last_activity 时按 created_at 计算闲置时长。"""
    repo = _git_repo(tmp_path / "repo", "main")
    wt = _clean_worktree(tmp_path / "wt")
    row = _stale("lane-old", str(wt))
    row.pop("last_activity")
    row["created_at"] = _iso_ago(10)
    audit = _ledger(tmp_path / "audit", [row])
    assert (
        check_git_main_write(
            "git commit -m x", audit_dir=audit, session_id="me", workdir=str(repo)
        )
        is None
    )


def test_push_src_only_head_on_main_detected(tmp_path):
    """R6：`git push origin HEAD`（main 工作树）就是在推 main，不能漏判。"""
    repo = _git_repo(tmp_path / "repo", "main")
    audit = _ledger(tmp_path / "audit", [_lane("lane-m", "verifying", "sess-other")])
    for cmd in ("git push origin HEAD", "git push origin @"):
        out = check_git_main_write(
            cmd, audit_dir=audit, session_id="me", workdir=str(repo)
        )
        assert out is not None and out["reason_code"] == "main_push_closing_lane", cmd


def test_push_option_value_not_taken_as_remote(tmp_path):
    """R6：`-o ci.skip` 的值是数据，不能顶替 remote（否则快进校验被 fail-open 绕过）。"""
    repo = _git_repo(tmp_path / "repo", "main")
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(bare)], check=True)
    ahead = tmp_path / "ahead"
    subprocess.run(["git", "clone", "-q", str(bare), str(ahead)], check=True)
    for key, val in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(ahead), "config", key, val], check=True)
    (ahead / "b.txt").write_text("y")
    subprocess.run(["git", "-C", str(ahead), "add", "."], check=True)
    subprocess.run(["git", "-C", str(ahead), "commit", "-qm", "ahead"], check=True)
    subprocess.run(
        ["git", "-C", str(ahead), "push", "-q", "origin", "HEAD:main"], check=True
    )
    audit = _ledger(tmp_path / "audit", [_lane("lane-o", "active", "sess-other")])
    out = check_git_main_write(
        f"git push -o ci.skip {bare} main",
        audit_dir=audit,
        session_id="me",
        workdir=str(repo),
    )
    assert out is not None and out["reason_code"] == "main_push_not_fast_forward"


def test_push_wildcard_refspec_widened(tmp_path):
    """R6：通配 dst 可能写到 main → 按 --all 宽判据（open lane 也拦）。"""
    repo = _git_repo(tmp_path / "repo", "main")
    audit = _ledger(tmp_path / "audit", [_lane("lane-w", "active", "sess-other")])
    out = check_git_main_write(
        "git push origin refs/heads/*:refs/heads/*",
        audit_dir=audit,
        session_id="me",
        workdir=str(repo),
    )
    assert out is not None and out["reason_code"] == "main_push_all_other_lane"


# --- R9（P1 修复）：`--repo` 不建模 → fail-closed 拒绝 ---


def test_push_repo_option_denied_as_unmodeled(tmp_path):
    """`git push --repo <url> main`：远端不在位置参数里 → 不猜语义，直接拒绝。"""
    repo = _git_repo(tmp_path / "repo", "feat/me")
    audit = _ledger(tmp_path / "audit", [_lane("lane-r", "merging", "sess-other")])
    out = check_git_main_write(
        "git push --repo origin main",
        audit_dir=audit,
        session_id="me",
        workdir=str(repo),
    )
    assert out is not None and out["reason_code"] == "main_push_repo_option_unmodeled"


def test_push_repo_equals_form_denied_as_unmodeled(tmp_path):
    """内联 `--repo=<url>` 同样不建模。"""
    repo = _git_repo(tmp_path / "repo", "feat/me")
    audit = _ledger(tmp_path / "audit", [_lane("lane-r2", "verifying", "sess-other")])
    out = check_git_main_write(
        "git push --repo=origin refs/heads/main:refs/heads/main",
        audit_dir=audit,
        session_id="me",
        workdir=str(repo),
    )
    assert out is not None and out["reason_code"] == "main_push_repo_option_unmodeled"


def test_push_repo_option_denied_even_for_feature_refspec(tmp_path):
    """fail-closed 的代价：推特性分支也用 --repo 时一并拒绝（可改写为 <remote> <refspec>）。"""
    repo = _git_repo(tmp_path / "repo", "feat/me")
    audit = _ledger(tmp_path / "audit", [_lane("lane-r3", "merging", "sess-other")])
    out = check_git_main_write(
        "git push --repo origin feat/me",
        audit_dir=audit,
        session_id="me",
        workdir=str(repo),
    )
    assert out is not None and out["reason_code"] == "main_push_repo_option_unmodeled"


def test_push_repo_option_allowed_without_other_lanes(tmp_path):
    """没有任何他人 lane 时闸本就不拦，--repo 也不例外。"""
    repo = _git_repo(tmp_path / "repo", "feat/me")
    audit = _ledger(tmp_path / "audit", [])
    assert (
        check_git_main_write(
            "git push --repo origin main",
            audit_dir=audit,
            session_id="me",
            workdir=str(repo),
        )
        is None
    )


def test_push_option_value_named_repo_not_taken_as_option(tmp_path):
    """`-o --repo` 里的 --repo 是 -o 的值，不能被当"远端由选项给出"（否则误拒/误放）。"""
    repo = _git_repo(tmp_path / "repo", "main")  # 当前分支 main；无 refspec 按当前分支判
    audit = _ledger(tmp_path / "audit", [_lane("lane-r4", "merging", "sess-other")])
    out = check_git_main_write(
        "git push origin -o --repo",
        audit_dir=audit,
        session_id="me",
        workdir=str(repo),
    )
    assert out is not None and out["reason_code"] == "main_push_closing_lane"


def test_push_is_non_ff_refuses_option_like_remote(tmp_path):
    """防御：远端名以 `-` 开头时不喂给 ls-remote，按非快进拒绝。"""
    repo = _git_repo(tmp_path / "repo", "main")
    assert guard_module._push_is_non_ff("main", "--upload-pack=x", str(repo)) is True
