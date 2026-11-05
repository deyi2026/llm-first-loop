"""BranchLane 账本单测：裁决 A2（1:1）、A9（CAS）、终态可归因、损坏 fail-closed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_loop.introspection.lane import (
    LaneConstraintError,
    LaneStore,
    LaneStoreCorruptionError,
    LaneVersionConflictError,
)


@pytest.fixture()
def store(tmp_path: Path) -> LaneStore:
    return LaneStore(tmp_path)


def _create(store: LaneStore, **overrides):
    payload = {
        "branch": "fix/a",
        "worktree": "/tmp/wt-a",
        "base_main_sha": "a" * 40,
        "goal_id": "goal-1",
        "owner_session_id": "s1",
        "paths": ["src/a.py"],
    }
    payload.update(overrides)
    return store.create(**payload)


def test_create_and_get_roundtrip(store: LaneStore) -> None:
    lane = _create(store)
    assert lane.lane_id.startswith("lane-")
    assert lane.status == "open"
    assert lane.version == 1
    assert lane.lane_role == "main"

    got = store.get(lane.lane_id)
    assert got is not None
    assert got["branch"] == "fix/a"
    assert got["goal_id"] == "goal-1"


def test_goal_one_to_one_rejects_second_main_lane(store: LaneStore) -> None:
    _create(store)
    with pytest.raises(LaneConstraintError, match="至多一条在途 main lane"):
        _create(store, branch="fix/b", worktree="/tmp/wt-b")
    # 并行拆分场景：sub lane 允许复用同一 goal
    sub = _create(store, branch="fix/b", worktree="/tmp/wt-b", lane_role="sub")
    assert sub.lane_role == "sub"


def test_terminal_lane_frees_the_goal_slot(store: LaneStore) -> None:
    first = _create(store)
    store.close(first.lane_id, expected_version=1, status="merged", reason="merged in batch-1")
    second = _create(store, branch="fix/c", worktree="/tmp/wt-c")
    assert second.goal_id == "goal-1"


def test_branch_and_worktree_uniqueness(store: LaneStore) -> None:
    _create(store)
    with pytest.raises(LaneConstraintError, match="branch 已被在途 lane 占用"):
        _create(store, worktree="/tmp/wt-b", lane_role="sub", goal_id="goal-1")
    with pytest.raises(LaneConstraintError, match="worktree 已被在途 lane 占用"):
        _create(store, branch="fix/b", lane_role="sub")


def test_version_cas_conflict(store: LaneStore) -> None:
    lane = _create(store)
    updated = store.update(lane.lane_id, expected_version=1, head_sha="b" * 40)
    assert updated["version"] == 2
    with pytest.raises(LaneVersionConflictError) as exc:
        store.update(lane.lane_id, expected_version=1, head_sha="c" * 40)
    assert exc.value.current == 2
    # 冲突不得写入
    assert store.get(lane.lane_id)["head_sha"] == "b" * 40


def test_unknown_field_is_rejected_not_silently_dropped(store: LaneStore) -> None:
    lane = _create(store)
    with pytest.raises(LaneConstraintError, match="不可更新字段"):
        store.update(lane.lane_id, expected_version=1, owner_session_id="hijack")


def test_terminal_status_is_irreversible(store: LaneStore) -> None:
    lane = _create(store)
    store.close(lane.lane_id, expected_version=1, status="abandoned", reason="superseded")
    with pytest.raises(LaneConstraintError, match="终态不可逆"):
        store.update(lane.lane_id, expected_version=2, status="active")


def test_close_requires_reason_and_is_idempotent(store: LaneStore) -> None:
    lane = _create(store)
    with pytest.raises(LaneConstraintError, match="非空 reason"):
        store.close(lane.lane_id, expected_version=1, status="merged", reason="   ")
    first = store.close(lane.lane_id, expected_version=1, status="merged", reason="batch-1")
    again = store.close(lane.lane_id, expected_version=2, status="merged", reason="batch-1")
    assert first["status"] == again["status"] == "merged"
    assert again["version"] == 2  # 幂等不递增


def test_list_hides_terminal_by_default(store: LaneStore) -> None:
    a = _create(store)
    _create(store, branch="fix/b", worktree="/tmp/wt-b", goal_id="goal-2")
    store.close(a.lane_id, expected_version=1, status="closed", reason="done")

    visible = store.list()
    assert [row["goal_id"] for row in visible] == ["goal-2"]
    assert len(store.list(include_terminal=True)) == 2


def test_corrupt_line_fails_closed(store: LaneStore, tmp_path: Path) -> None:
    lane = _create(store)
    path = tmp_path / "lanes.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    with pytest.raises(LaneStoreCorruptionError):
        store.list()
    with pytest.raises(LaneStoreCorruptionError):
        store.update(lane.lane_id, expected_version=1, head_sha="d" * 40)


def test_events_are_appended_for_audit(store: LaneStore, tmp_path: Path) -> None:
    lane = _create(store)
    store.update(lane.lane_id, expected_version=1, status="active")
    store.close(lane.lane_id, expected_version=2, status="merged", reason="batch-1")

    events = [
        json.loads(line)
        for line in (tmp_path / "lane_events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [e["event"] for e in events] == ["lane.created", "lane.updated", "lane.closed"]
    assert events[-1]["reason"] == "batch-1"


def test_paths_normalized_and_deduplicated(store: LaneStore) -> None:
    lane = _create(store, paths=["src/b.py", " src/a.py ", "src/b.py", ""])
    assert lane.paths == ["src/a.py", "src/b.py"]
