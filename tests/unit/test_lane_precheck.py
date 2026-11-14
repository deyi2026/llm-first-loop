"""P4 开门预检（DESIGN-20261114 §4.5 / R4）：只告警不阻断、纯读、goal 开关.

验收对应:
- R4-a: paths 与在途 lane 交叉 → 回执含 overlap_warning 且登记成功
- R4-b: goal_id 不在 goals.jsonl → 默认成功且带 goal_unknown；lane_require_goal=true 才硬拒
- R4-c: create() 返回值类型不变（预检只在回执侧附加）
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.lane import Lane, LaneStore
from llm_loop.introspection.tools_lane import run_lane_open


class _Host:
    def __init__(self, audit_dir: Path, *, require_goal: bool = False) -> None:
        self.audit_dir = str(audit_dir)
        self.ctx = None
        self.lane_require_goal = require_goal


@pytest.fixture()
def host(tmp_path: Path) -> _Host:
    return _Host(tmp_path)


def _open(host: _Host, **kw):
    args = {"branch": "fix/x", "worktree": "/tmp/wt-x", "goal_id": "goal-9", "paths": ["src/x.py"]}
    args.update(kw)
    return run_lane_open(None, host, args)


def _lane_id(result) -> str:
    for token in result.content.split():
        if token.startswith("lane_id="):
            return token.split("=", 1)[1]
    raise AssertionError(f"no lane_id in: {result.content}")


def _seed_goal(audit_dir: Path, goal_id: str) -> None:
    (audit_dir / "goals.jsonl").write_text(
        json.dumps({"id": goal_id, "objective": "seed"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_precheck_is_pure_read(host: _Host, tmp_path: Path) -> None:
    """R2-a 同款口径：预检不得改动 lanes.jsonl。"""
    _open(host)
    store = LaneStore(tmp_path)
    before = _sha(tmp_path / "lanes.jsonl")
    store.precheck(branch="fix/y", worktree="/tmp/wt-y", goal_id="goal-9", paths=["src/y.py"])
    assert _sha(tmp_path / "lanes.jsonl") == before


def test_overlap_warning_does_not_block(host: _Host) -> None:
    """R4-a：重叠只告警，登记必须成功，且指名对端 lane 与共享路径.

    第二条 lane 必须用不同 goal：同 goal 的第二条 main lane 会被 _assert_unique
    硬拒，那是 1:1 裁决（另一个门），不能拿来测「paths 重叠只告警」。
    """
    first = _lane_id(_open(host, paths=["src/shared.py"]))
    result = _open(
        host, branch="fix/y", worktree="/tmp/wt-y", goal_id="goal-10",
        paths=["src/shared.py"],
    )
    assert result.status is ToolResultStatus.SUCCESS
    assert "路径重叠告警" in result.content
    assert first in result.content
    assert "src/shared.py" in result.content
    assert _lane_id(result)


def test_terminal_lane_excluded_from_overlap(host: _Host) -> None:
    """终态 lane 不应再制造重叠告警（否则告警全是历史噪声）。"""
    first = _lane_id(_open(host, paths=["src/shared.py"]))
    LaneStore(str(host.audit_dir)).close(
        first, expected_version=1, status="merged", reason="merged in batch-1"
    )
    result = _open(host, branch="fix/y", worktree="/tmp/wt-y", paths=["src/shared.py"])
    assert result.status is ToolResultStatus.SUCCESS
    assert "路径重叠告警" not in result.content


def test_goal_unknown_warns_but_registers(host: _Host) -> None:
    """R4-b 默认档：goal 不在账本 → 登记成功 + 告警（不切断探针用法）。"""
    result = _open(host, goal_id="diagnostic-nonexistent-goal")
    assert result.status is ToolResultStatus.SUCCESS
    assert "goal 告警" in result.content
    assert "diagnostic-nonexistent-goal" in result.content


def test_goal_known_has_no_warning(host: _Host, tmp_path: Path) -> None:
    _seed_goal(tmp_path, "goal-9")
    result = _open(host, goal_id="goal-9")
    assert result.status is ToolResultStatus.SUCCESS
    assert "goal 告警" not in result.content


def test_goal_unknown_hard_reject_when_enabled(tmp_path: Path) -> None:
    """R4-b 开关档：lane_require_goal=true 时才是硬拒。"""
    host = _Host(tmp_path, require_goal=True)
    result = _open(host, goal_id="goal-missing")
    assert result.status is ToolResultStatus.FAILURE
    assert "goal_not_found" in result.content


def test_goal_known_passes_when_enabled(tmp_path: Path) -> None:
    host = _Host(tmp_path, require_goal=True)
    _seed_goal(tmp_path, "goal-ok")
    result = _open(host, goal_id="goal-ok")
    assert result.status is ToolResultStatus.SUCCESS


def test_create_return_type_unchanged(host: _Host, tmp_path: Path) -> None:
    """R4-c：预检只在回执侧附加，create() 仍返回 Lane 实例。"""
    lane = LaneStore(str(host.audit_dir)).create(
        branch="fix/z", worktree="/tmp/wt-z", base_main_sha="b" * 40, goal_id="goal-9"
    )
    assert isinstance(lane, Lane)
    assert lane.lane_id.startswith("lane-")


def test_precheck_failure_degrades_without_blocking(host: _Host, monkeypatch) -> None:
    """预检自身异常不得阻断登记——它是附加信息，不是门禁。"""
    store = LaneStore(str(host.audit_dir))

    def _boom(**_kw):
        raise RuntimeError("synthetic precheck failure")

    monkeypatch.setattr(LaneStore, "precheck", _boom)
    result = _open(host, branch="fix/d", worktree="/tmp/wt-d")
    assert result.status is ToolResultStatus.SUCCESS
    assert "预检不可用" in result.content
    assert _lane_id(result)
    # 确认 store 实例仍可正常读账本（未因预检异常留下半写状态）
    assert store.get(_lane_id(result)) is not None
