# batch1 lane B: M4-A contract_changes same-key hint tests
"M4-A: contract_changes 同键确定性提示——纯提示、零阻断、零审批。"
# 触发面: lane_open（precheck）与 lane_queue_submit（回执）。
# 判定: 另一在途 lane（非终态、非自身）的 contract_changes 含相同键 → 提示
# 键名 + 对方 lane_id/goal_id；同键 ≠ 设计冲突（语义由模型/人判）。
# 边界: 对方终态不提示；空/缺失无提示不报错；不提示自身；多 lane 逐项
# 列全且 (key, lane_id) 排序稳定（确定性输出）。

from __future__ import annotations

import hashlib
from pathlib import Path

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.lane import LaneStore
from llm_loop.introspection.tools_lane import run_lane_open
from llm_loop.introspection.tools_merge_queue import run_lane_queue_submit


class _Host:
    def __init__(self, audit_dir: Path) -> None:
        self.audit_dir = str(audit_dir)
        self.ctx = None


def _open(host: _Host, **kw):
    args = {
        "branch": "fix/x",
        "worktree": "/tmp/wt-x",
        "goal_id": "goal-9",
        "paths": ["src/x.py"],
    }
    args.update(kw)
    return run_lane_open(None, host, args)


def _lane_id(result) -> str:
    for token in result.content.split():
        if token.startswith("lane_id="):
            return token.split("=", 1)[1]
    raise AssertionError(f"no lane_id in: {result.content}")


def _seed_lane(audit_dir: Path, **kw) -> str:
    args: dict = {
        "branch": "fix/seed",
        "worktree": "/tmp/wt-seed",
        "goal_id": "goal-seed",
        "base_main_sha": "a" * 40,
    }
    args.update(kw)
    lane = LaneStore(str(audit_dir)).create(**args)
    return lane.lane_id


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------- lane_open（precheck 触发面） ----------------


def test_same_key_hint_in_lane_open_receipt(tmp_path: Path) -> None:
    "同键 → lane_open 回执提示键名 + 对方 lane_id/goal_id，登记仍成功（零阻断）。"
    host = _Host(tmp_path)
    other = _seed_lane(
        tmp_path,
        branch="fix/other",
        worktree="/tmp/wt-other",
        goal_id="goal-other",
        contract_changes=["KEY_RATE_LIMIT"],
    )
    result = _open(
        host,
        branch="fix/mine",
        worktree="/tmp/wt-mine",
        goal_id="goal-mine",
        contract_changes=["KEY_RATE_LIMIT", "KEY_CACHE"],
    )
    assert result.status is ToolResultStatus.SUCCESS
    assert "同键声明提示" in result.content
    assert "非冲突" in result.content
    assert "KEY_RATE_LIMIT" in result.content
    assert other in result.content
    assert "goal-other" in result.content
    assert _lane_id(result)


def test_no_hint_when_no_shared_key(tmp_path: Path) -> None:
    "键不相交 → 无提示（零噪声）。"
    host = _Host(tmp_path)
    _seed_lane(
        tmp_path,
        branch="fix/other",
        worktree="/tmp/wt-other",
        goal_id="goal-other",
        contract_changes=["KEY_A"],
    )
    result = _open(
        host,
        branch="fix/mine",
        worktree="/tmp/wt-mine",
        goal_id="goal-mine",
        contract_changes=["KEY_B"],
    )
    assert result.status is ToolResultStatus.SUCCESS
    assert "同键声明提示" not in result.content


def test_terminal_lane_not_hinted(tmp_path: Path) -> None:
    "对方终态 → 不提示（历史 lane 不制造噪声）。"
    host = _Host(tmp_path)
    other = _seed_lane(
        tmp_path,
        branch="fix/other",
        worktree="/tmp/wt-other",
        goal_id="goal-other",
        contract_changes=["KEY_RATE_LIMIT"],
    )
    LaneStore(str(tmp_path)).close(
        other, expected_version=1, status="merged", reason="merged in batch-0"
    )
    result = _open(
        host,
        branch="fix/mine",
        worktree="/tmp/wt-mine",
        goal_id="goal-mine",
        contract_changes=["KEY_RATE_LIMIT"],
    )
    assert result.status is ToolResultStatus.SUCCESS
    assert "同键声明提示" not in result.content


def test_empty_or_missing_contract_changes_no_hint_no_error(tmp_path: Path) -> None:
    "本次 contract_changes 空/缺失，或对方无 contract_changes → 无提示不报错。"
    host = _Host(tmp_path)
    _seed_lane(
        tmp_path,
        branch="fix/other",
        worktree="/tmp/wt-other",
        goal_id="goal-other",
        contract_changes=["KEY_A"],
    )
    result = _open(
        host, branch="fix/mine1", worktree="/tmp/wt-mine1", goal_id="goal-mine1"
    )
    assert result.status is ToolResultStatus.SUCCESS
    assert "同键声明提示" not in result.content

    result2 = _open(
        host,
        branch="fix/mine2",
        worktree="/tmp/wt-mine2",
        goal_id="goal-mine2",
        contract_changes=["KEY_Z"],
    )
    assert result2.status is ToolResultStatus.SUCCESS
    assert "同键声明提示" not in result2.content

    store = LaneStore(str(tmp_path))
    out = store.precheck(
        branch="fix/mine3",
        worktree="/tmp/wt-mine3",
        goal_id="goal-mine3",
        paths=[],
        contract_changes=[],
    )
    assert out.get("contract_same_key_warning") == []


def test_precheck_same_key_deterministic_sorted_and_pure(tmp_path: Path) -> None:
    "同键多 lane → 逐项列全、(key, lane_id) 稳定排序、纯读零写。"
    a = _seed_lane(
        tmp_path,
        branch="fix/a",
        worktree="/tmp/wt-a",
        goal_id="goal-a",
        contract_changes=["KEY_ONE"],
    )
    b = _seed_lane(
        tmp_path,
        branch="fix/b",
        worktree="/tmp/wt-b",
        goal_id="goal-b",
        contract_changes=["KEY_TWO"],
    )
    c = _seed_lane(
        tmp_path,
        branch="fix/c",
        worktree="/tmp/wt-c",
        goal_id="goal-c",
        contract_changes=["KEY_ONE", "KEY_TWO"],
    )
    store = LaneStore(str(tmp_path))
    before = _sha(tmp_path / "lanes.jsonl")
    out1 = store.precheck(
        branch="fix/mine",
        worktree="/tmp/wt-mine",
        goal_id="goal-mine",
        paths=[],
        contract_changes=["KEY_TWO", "KEY_ONE"],
    )
    out2 = store.precheck(
        branch="fix/mine",
        worktree="/tmp/wt-mine",
        goal_id="goal-mine",
        paths=[],
        contract_changes=["KEY_ONE", "KEY_TWO"],
    )
    assert _sha(tmp_path / "lanes.jsonl") == before
    items1 = out1["contract_same_key_warning"]
    assert items1 == out2["contract_same_key_warning"]
    got = [(h["key"], h["lane_id"]) for h in items1]
    assert got == sorted(got)
    assert len(items1) == 4
    by_key = {}
    for h in items1:
        by_key.setdefault(h["key"], set()).add(h["lane_id"])
        assert h["goal_id"]
    assert by_key["KEY_ONE"] == {a, c}
    assert by_key["KEY_TWO"] == {b, c}


def test_hint_helper_excludes_self_and_terminal(tmp_path: Path) -> None:
    "LaneStore 同键提示: 排除自身与终态；mine 为空返回空。"
    store = LaneStore(str(tmp_path))
    mine = _seed_lane(
        tmp_path,
        branch="fix/mine",
        worktree="/tmp/wt-mine",
        goal_id="goal-mine",
        contract_changes=["KEY_ONE"],
    )
    _seed_lane(
        tmp_path,
        branch="fix/other",
        worktree="/tmp/wt-other",
        goal_id="goal-other",
        contract_changes=["KEY_ONE"],
    )
    mine_keys = ["KEY_ONE"]
    only_other = store.contract_same_key_hint(mine=mine_keys, exclude_lane_id=mine)
    assert [h["lane_id"] for h in only_other]
    assert mine not in [h["lane_id"] for h in only_other]
    with_self = store.contract_same_key_hint(mine=mine_keys)
    assert {h["lane_id"] for h in with_self} == {mine} | {
        h["lane_id"] for h in only_other
    }
    assert store.contract_same_key_hint(mine=[], exclude_lane_id=mine) == []
    for h in with_self:
        row = store.get(h["lane_id"])
        assert row is not None
        store.close(
            h["lane_id"],
            expected_version=row["version"],
            status="closed",
            reason="done",
        )
    assert store.contract_same_key_hint(mine=mine_keys, exclude_lane_id=mine) == []


# ---------------- lane_queue_submit（回执触发面） ----------------


def _submit(host: _Host, lane_id: str):
    return run_lane_queue_submit(
        None,
        host,
        {
            "lane_id": lane_id,
            "head_sha": "b" * 40,
            "base_main_sha": "a" * 40,
            "paths": ["src/mine.py"],
        },
    )


def test_queue_submit_receipt_carries_same_key_hint(tmp_path: Path) -> None:
    "同键 → queue_submit 回执带确定性提示；入队主流程不受影响（零阻断）。"
    host = _Host(tmp_path)
    other = _seed_lane(
        tmp_path,
        branch="fix/other",
        worktree="/tmp/wt-other",
        goal_id="goal-other",
        contract_changes=["KEY_RATE_LIMIT"],
    )
    mine = _seed_lane(
        tmp_path,
        branch="fix/mine",
        worktree="/tmp/wt-mine",
        goal_id="goal-mine",
        contract_changes=["KEY_RATE_LIMIT"],
    )
    result = _submit(host, mine)
    assert result.status is ToolResultStatus.SUCCESS
    assert "同键声明提示" in result.content
    assert "非冲突" in result.content
    assert "KEY_RATE_LIMIT" in result.content
    assert other in result.content
    assert "goal-other" in result.content


def test_queue_submit_no_shared_key_silent(tmp_path: Path) -> None:
    "queue_submit: 无同键 → 零噪声（回执不携带提示段）。"
    host = _Host(tmp_path)
    mine = _seed_lane(
        tmp_path,
        branch="fix/mine",
        worktree="/tmp/wt-mine",
        goal_id="goal-mine",
        contract_changes=["KEY_ONLY_MINE"],
    )
    result = _submit(host, mine)
    assert result.status is ToolResultStatus.SUCCESS
    assert "同键声明提示" not in result.content
