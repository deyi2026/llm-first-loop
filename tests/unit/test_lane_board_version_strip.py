"""W1：Board 版本条带（BUG-16/OPT-11）与 lane 版本聚合（BUG-14a）.

硬约束:
- Board 只能把**可核验的 origin/main** 标成 main_head；worktree checkout HEAD 另列，
  绝不冒充 main（detached 场景是真实误报来源）。
- 来源不可核验 → 显式 unknown + degraded，不伪造 sha。
- 同 lane_id 历史多行：按最高 version 取终态；同版本冲突/坏版本 fail-closed，
  仍进 degraded（R5 写命令安全门不放宽，本模块只读聚合）。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from llm_loop.introspection.lane_board import build_board
from llm_loop.web.routes import router as web_router

BOARD_PATH = "/api/v1/coordination/board"


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _repo_with_origin_main(tmp_path: Path) -> tuple[Path, str, str]:
    """repo 处于 detached HEAD=old，origin/main=new（复现真实误报场景）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "tester")
    (repo / "a.txt").write_text("a", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "first")
    old = _git(repo, "rev-parse", "HEAD")
    (repo / "a.txt").write_text("b", encoding="utf-8")
    _git(repo, "commit", "-qam", "second")
    new = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/main", new)
    _git(repo, "checkout", "-q", "--detach", old)
    return repo, old, new


def _ledger(audit: Path, rows: list[dict]) -> None:
    audit.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    (audit / "lanes.jsonl").write_text(body, encoding="utf-8")


def _lane(lane_id: str, status: str, version: int, **extra: object) -> dict:
    row = {
        "lane_id": lane_id,
        "branch": "feat/" + lane_id,
        "worktree": "/tmp/wt-" + lane_id,
        "base_main_sha": "a" * 40,
        "goal_id": "goal-x",
        "paths": ["src/llm_loop/web"],
        "status": status,
        "version": version,
        "created_at": "2026-11-16T01:00:00+08:00",
    }
    row.update(extra)
    return row


# ---------------- BUG-16：main_head 必须可核验 ----------------


def test_main_head_comes_from_verified_origin_main_not_worktree_head(tmp_path: Path) -> None:
    repo, old, new = _repo_with_origin_main(tmp_path)
    board = build_board(tmp_path / "audit", workspace_root=str(repo))

    assert board["main_head"] == new
    main = board["versions"]["main"]
    assert main["head"] == new
    # P2: origin/main 只是本地 remote-tracking ref——不得宣称远端已核验。
    assert main["source"] == "local_tracking"
    assert main["ref"] == "origin/main"
    assert main["remote_verified"] is False
    assert main["freshness"] == "unknown"
    worktree = board["versions"]["worktree"]
    assert worktree["head"] == old
    assert worktree["detached"] is True
    assert worktree["behind_main"] == 1
    assert board["main_head"] != worktree["head"], "worktree HEAD 不得冒充 main"


def test_origin_main_missing_is_explicit_unknown(tmp_path: Path) -> None:
    repo, old, _ = _repo_with_origin_main(tmp_path)
    _git(repo, "update-ref", "-d", "refs/remotes/origin/main")

    board = build_board(tmp_path / "audit", workspace_root=str(repo))

    assert board["main_head"] == ""
    assert board["versions"]["main"]["source"] == "unknown"
    assert board["versions"]["worktree"]["head"] == old
    assert "main_head_unknown" in board["degraded"]
    assert "origin_main_unavailable" in board["degraded"]
    assert board["deployment"]["in_sync"] is False
    assert board["deployment"]["sync_state"] == "unknown"


def test_explicit_main_head_stays_supported(tmp_path: Path) -> None:
    board = build_board(tmp_path / "audit", main_head="b" * 40)

    assert board["main_head"] == "b" * 40
    assert board["versions"]["main"]["head"] == "b" * 40
    assert board["versions"]["main"]["source"] == "explicit"
    assert board["versions"]["main"]["remote_verified"] is False


# ---------------- OPT-11：desired / live 分段可核验 ----------------


def test_desired_and_live_are_separate_verifiable_segments(tmp_path: Path) -> None:
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "managed_service_deployment.json").write_text(
        json.dumps(
            {
                "schema": "managed-service-deployment/v1",
                "deployment_id": "deploy-1",
                "generation": 425,
                "git_head": "b" * 40,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "restart-receipt.json").write_text(
        json.dumps(
            {
                "ts": "2026-11-16T15:23:31+08:00",
                "action": "wecom",
                "git_head_full": "b" * 40,
                "target_sha": "b" * 40,
                "authoritative": True,
            }
        ),
        encoding="utf-8",
    )

    board = build_board(tmp_path / "audit")
    versions = board["versions"]

    assert versions["desired"]["generation"] == 425
    assert versions["desired"]["sha"] == "b" * 40
    assert versions["desired"]["source"] == "managed_service_deployment"
    assert versions["live"]["sha"] == "b" * 40
    assert versions["live"]["source"] == "restart-receipt"
    assert board["deployment"]["desired_generation"] == 425
    assert board["deployment"]["desired_matches_live"] is True


def test_desired_missing_is_unknown_not_guessed(tmp_path: Path) -> None:
    board = build_board(tmp_path / "audit")

    assert board["versions"]["desired"]["source"] == "unknown"
    assert board["versions"]["desired"]["generation"] is None
    assert board["versions"]["desired"]["sha"] == ""
    assert board["deployment"]["desired_matches_live"] is None
    assert "desired_deployment_missing" in board["degraded"]


# ---------------- BUG-14a：同 ID 多版本聚合 ----------------


def test_superseded_duplicate_does_not_create_ghost_lane(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _ledger(
        audit,
        [
            _lane("lane-ghost", "active", 1),
            _lane("lane-ghost", "closed", 2),
            _lane("lane-real", "active", 1),
        ],
    )

    board = build_board(audit)

    assert [row["lane_id"] for row in board["lanes"]] == ["lane-real"]
    assert board["summary"]["inflight"] == 1
    assert board["summary"]["duplicate_lane_ids"] == ["lane-ghost"]
    assert board["summary"]["lane_conflicts"] == []
    assert not any(d.startswith("lane_version_conflict") for d in board["degraded"])


def test_same_version_conflicting_status_fails_closed(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _ledger(
        audit,
        [
            _lane("lane-conflict", "active", 2),
            _lane("lane-conflict", "closed", 2),
            _lane("lane-ok", "active", 1),
        ],
    )

    board = build_board(audit)

    assert [row["lane_id"] for row in board["lanes"]] == ["lane-ok"]
    assert board["summary"]["lane_conflicts"] == ["lane-conflict"]
    assert "lane_version_conflict:lane-conflict" in board["degraded"]


def test_invalid_version_fails_closed(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    _ledger(
        audit,
        [
            _lane("lane-badver", "active", "2"),  # type: ignore[arg-type]
            _lane("lane-ok", "active", 1),
        ],
    )

    board = build_board(audit)

    assert [row["lane_id"] for row in board["lanes"]] == ["lane-ok"]
    assert "lane_version_invalid:lane-badver" in board["degraded"]


def test_unreadable_ledger_still_degrades_without_raising(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    audit.mkdir(parents=True)
    (audit / "lanes.jsonl").write_text("{not json\n", encoding="utf-8")

    board = build_board(audit)

    assert board["lanes"] == []
    assert any(d.startswith("lanes_unreadable") for d in board["degraded"])


# ---------------- 路由投影 ----------------


def test_board_route_projects_versions(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    app = FastAPI()
    app.include_router(web_router)
    app.state.engine = SimpleNamespace(
        settings=SimpleNamespace(data_dir=str(data_dir)),
        workspace_root=str(tmp_path / "no-such-workspace"),
    )
    client = TestClient(app)

    resp = client.get(BOARD_PATH)

    assert resp.status_code == 200
    body = resp.json()
    assert body["versions"]["main"]["source"] == "unknown"
    assert body["versions"]["worktree"]["head"] == ""
    assert body["main_head"] == ""


# ---------------- P1-A：历史 deployments 不得冒充 live ----------------


def _legacy_deployment(audit: Path, sha: str) -> None:
    dep = audit / "deployments"
    dep.mkdir(parents=True, exist_ok=True)
    (dep / "old.jsonl").write_text(
        json.dumps({"ts": "2025-01-01T00:00:00+08:00", "target_sha": sha}) + "\n",
        encoding="utf-8",
    )


def _desired_file(tmp_path: Path, sha: str, generation: int = 425) -> None:
    (tmp_path / "runtime").mkdir(exist_ok=True)
    (tmp_path / "runtime" / "managed_service_deployment.json").write_text(
        json.dumps(
            {
                "schema": "managed-service-deployment/v1",
                "deployment_id": "deploy-1",
                "generation": generation,
                "git_head": sha,
            }
        ),
        encoding="utf-8",
    )


def test_legacy_deployment_cannot_pose_as_live(tmp_path: Path) -> None:
    """restart-receipt 缺失时，历史 deployments 行不得被当成"实际在跑"。"""
    sha = "a" * 40
    _legacy_deployment(tmp_path / "audit", sha)
    _desired_file(tmp_path, sha)

    # head 与历史行恰好同 sha——正是最容易被误判成 exact 的场景。
    board = build_board(tmp_path / "audit", main_head=sha)
    versions = board["versions"]

    # versions.live 只有权威回执能证明；缺失即 unknown，不拿历史行顶替。
    assert versions["live"]["sha"] == ""
    assert versions["live"]["source"] == "unknown"
    assert versions["live"]["authoritative"] is False
    # P2-1：live 的时间戳同样只能由权威回执提供，历史行的时间不得借用。
    assert versions["live"]["recorded_at"] == ""
    # 无法比较，必须是 None，不能因为在库上相等就报 True。
    assert board["deployment"]["desired_matches_live"] is None
    # 非权威 fallback 不得显示 verified exact（假绿）。
    assert board["deployment"]["in_sync"] is False
    assert board["deployment"]["sync_state"] == "unverified"
    assert "restart_receipt_missing" in board["degraded"]
    # legacy 字段兼容保留：历史行仍可读，但带权威标记。
    assert board["deployment"]["deployed_sha"] == sha
    assert board["deployment"]["deployed_authoritative"] is False


def test_authoritative_receipt_still_reports_exact(tmp_path: Path) -> None:
    sha = "a" * 40
    _desired_file(tmp_path, sha)
    (tmp_path / "restart-receipt.json").write_text(
        json.dumps(
            {
                "ts": "2026-11-16T15:23:31+08:00",
                "action": "wecom",
                "git_head_full": sha,
                "authoritative": True,
            }
        ),
        encoding="utf-8",
    )

    board = build_board(tmp_path / "audit", main_head=sha)

    assert board["versions"]["live"]["sha"] == sha
    assert board["deployment"]["desired_matches_live"] is True
    assert board["deployment"]["sync_state"] == "exact"
    assert board["deployment"]["in_sync"] is True


# ---------------- P1-B：同版本 payload 冲突 fail-closed ----------------


def test_same_version_owner_session_conflict_fails_closed(tmp_path: Path) -> None:
    """同 id/version/status 但 owner 不同：静默取首行会掩盖双写，必须排除+降级。"""
    audit = tmp_path / "audit"
    _ledger(
        audit,
        [
            _lane("lane-split", "active", 3, owner_session_id="owner-A"),
            _lane("lane-split", "active", 3, owner_session_id="owner-B"),
            _lane("lane-ok", "active", 1),
        ],
    )

    board = build_board(audit)

    assert [row["lane_id"] for row in board["lanes"]] == ["lane-ok"]
    assert board["summary"]["lane_conflicts"] == ["lane-split"]
    assert "lane_version_conflict:lane-split" in board["degraded"]


def test_identical_duplicate_row_is_tolerated(tmp_path: Path) -> None:
    """同一行被重复 append（完全一致）是可兼容的历史噪声，不算冲突。"""
    audit = tmp_path / "audit"
    row = _lane("lane-dup", "active", 1, owner_session_id="owner-A")
    _ledger(audit, [row, dict(row)])

    board = build_board(audit)

    assert [r["lane_id"] for r in board["lanes"]] == ["lane-dup"]
    assert board["summary"]["lane_conflicts"] == []
    assert board["summary"]["duplicate_lane_ids"] == ["lane-dup"]
    assert not any(d.startswith("lane_version_conflict") for d in board["degraded"])


def test_three_same_version_rows_with_non_string_owner_fails_closed(tmp_path: Path) -> None:
    """三行同 version，其中 owner_session_id 是数字：仍必须判冲突，不得静默取首行。"""
    audit = tmp_path / "audit"
    _ledger(
        audit,
        [
            _lane("lane-split3", "active", 2, owner_session_id="owner-A"),
            _lane("lane-split3", "active", 2, owner_session_id="owner-B"),
            _lane("lane-split3", "active", 2, owner_session_id=123),
        ],
    )

    board = build_board(audit)

    assert all(row["lane_id"] != "lane-split3" for row in board["lanes"])
    assert board["summary"]["lane_conflicts"] == ["lane-split3"]
    assert "lane_version_conflict:lane-split3" in board["degraded"]


def test_non_string_git_head_is_not_exposed_as_sha(tmp_path: Path) -> None:
    """desired git_head 是 true/123 时不得被 str() 成 "True"/"123" 冒充 SHA。"""
    for bad in (True, 123, ["a" * 40], {"sha": "a" * 40}):
        case = tmp_path / ("case-" + type(bad).__name__ + str(bad)[:3].strip("[]{}"))
        case.mkdir()
        (case / "runtime").mkdir()
        (case / "runtime" / "managed_service_deployment.json").write_text(
            json.dumps({"deployment_id": "d1", "generation": 7, "git_head": bad}),
            encoding="utf-8",
        )

        board = build_board(case / "audit")

        desired = board["versions"]["desired"]
        assert desired["sha"] == "", f"git_head={bad!r} 不得成为 SHA"
        assert desired["source"] == "unknown"
        assert "desired_deployment_invalid" in board["degraded"]
        assert board["deployment"]["desired_sha"] == ""


def test_non_utf8_desired_file_degrades_instead_of_raising(tmp_path: Path) -> None:
    """真实非 UTF-8 字节：read_text 会抛 UnicodeDecodeError，必须收敛进 degraded。"""
    (tmp_path / "runtime").mkdir()
    # 0xff 0xfe 不是合法 UTF-8 序列，且刻意让内容看起来像半截 JSON。
    (tmp_path / "runtime" / "managed_service_deployment.json").write_bytes(
        b'{"git_head": "' + b"a" * 40 + b'", "deployment_id": "\xff\xfe"}'
    )

    board = build_board(tmp_path / "audit")

    desired = board["versions"]["desired"]
    assert desired["sha"] == ""
    assert desired["source"] == "unknown"
    assert any(d.startswith("desired_deployment_unreadable") for d in board["degraded"])


def test_explicit_main_head_is_the_behind_baseline(tmp_path: Path) -> None:
    """显式 main_head 时 behind_main 必须相对该值，不得仍算 HEAD..origin/main。"""
    repo, old, new = _repo_with_origin_main(tmp_path)
    # origin/main=new（behind=1）；显式 main_head=old（HEAD 本身，behind=0）。
    board = build_board(tmp_path / "audit", workspace_root=str(repo), main_head=old)

    assert board["versions"]["main"]["head"] == old
    assert board["versions"]["main"]["source"] == "explicit"
    assert board["versions"]["worktree"]["behind_main"] == 0

    # 基准在本地解析不到 → 必须 None，不得借 origin/main 的计数。
    unknown = build_board(tmp_path / "audit2", workspace_root=str(repo), main_head="f" * 40)
    assert unknown["versions"]["main"]["head"] == "f" * 40
    assert unknown["versions"]["worktree"]["behind_main"] is None
    assert unknown["versions"]["worktree"]["head"] == old
    assert new != old
