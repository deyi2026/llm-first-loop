"""Board 聚合：部署条带必须给、重叠可见、**零写副作用**（A6）."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from llm_loop.introspection.lane import LaneStore
from llm_loop.introspection.lane_board import build_board


def _snapshot(root: Path) -> dict[str, str]:
    """目录快照：相对路径 -> sha256；用于证明 Board 零写。"""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


@pytest.fixture()
def seeded(tmp_path: Path) -> Path:
    store = LaneStore(tmp_path)
    store.create(
        branch="fix/a",
        worktree="/tmp/wt-a",
        base_main_sha="a" * 40,
        goal_id="goal-1",
        paths=["src/llm_loop/web"],
    )
    store.create(
        branch="fix/b",
        worktree="/tmp/wt-b",
        base_main_sha="a" * 40,
        goal_id="goal-2",
        paths=["src/llm_loop/web/routes.py"],
        lane_role="main",
    )
    dep = tmp_path / "deployments"
    dep.mkdir()
    rows = [
        {"ts": "2026-09-16T06:00:00+00:00", "phase": "pre_deploy", "target_sha": "old" * 10},
        {"ts": "2026-11-05T01:00:00+00:00", "phase": "pre_deploy", "target_sha": "b" * 40},
    ]
    (dep / "batch.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return tmp_path


def test_board_is_zero_write(seeded: Path) -> None:
    before = _snapshot(seeded)
    build_board(seeded, main_head="b" * 40)
    after = _snapshot(seeded)
    assert before == after, "Board 必须零写副作用（A6）"


def test_board_reports_deployment_strip(seeded: Path) -> None:
    board = build_board(seeded, main_head="b" * 40)
    assert board["deployment"]["deployed_sha"] == "b" * 40
    assert board["deployment"]["in_sync"] is True
    assert board["main_head"] == "b" * 40


def test_board_detects_path_overlap(seeded: Path) -> None:
    board = build_board(seeded, main_head="b" * 40)
    overlaps = board["summary"]["overlaps"]
    assert len(overlaps) == 1
    assert set(overlaps[0]["shared_paths"]) == {"src/llm_loop/web", "src/llm_loop/web/routes.py"}


def test_board_survives_without_any_data(tmp_path: Path) -> None:
    board = build_board(tmp_path)
    assert board["lanes"] == []
    assert "deployments_missing" in board["degraded"]
    assert "main_head_unknown" in board["degraded"]


def test_board_never_creates_audit_dir(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-audit"
    board = build_board(missing)
    assert not missing.exists(), "A6：目录不存在时不得创建"
    assert "audit_missing" in board["degraded"]
