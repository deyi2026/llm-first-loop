"""DESIGN-20261101 §2.4/§6 (L4): Goal.version 单调递增 + expected_version CAS.

覆盖:
- version 初值 1；checkpoint/update 成功后 +1
- get_goal 回执追加「版本: N」行（既有行不变）
- expected_version 匹配 → 写入成功；不匹配 → FAILURE + reason_code=version_conflict 且记录未改
- 旧记录缺 version 字段 → 按 1 起算（兼容读取，不重写历史）
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from llm_loop.core.message import ToolResultStatus
from llm_loop.core.run_context import current_session_id as _sid
from llm_loop.introspection.goal import GoalStore
from llm_loop.introspection.tools_goal import run_checkpoint_goal, run_get_goal, run_update_goal

OWNER = "sess-owner-l4"


def _bind(sid: str):
    return _sid.set(sid)


@pytest.fixture(autouse=True)
def _reset_sid():
    token = _sid.set(OWNER)
    yield
    _sid.reset(token)


def _host(tmp_path):
    return SimpleNamespace(audit_dir=str(tmp_path), ctx=SimpleNamespace())


def test_version_increments(tmp_path):
    store = GoalStore(str(tmp_path))
    g = store.create("版本推进目标", session_id=OWNER)
    assert store.get(g.id)["version"] == 1

    store.checkpoint(g.id, what="第一里程碑")
    assert store.get(g.id)["version"] == 2

    store.update(g.id, "blocked", "等人工")
    assert store.get(g.id)["version"] == 3
    assert GoalStore.version_of(store.get(g.id)) == 3


def test_get_goal_reports_version(tmp_path):
    g = GoalStore(str(tmp_path)).create("读版本", session_id=OWNER)
    res = run_get_goal(None, _host(tmp_path), {"goal_id": g.id})
    assert res.status == ToolResultStatus.SUCCESS
    assert "版本: 1" in res.content.split("\n")


def test_expected_version_match_allows_write(tmp_path):
    g = GoalStore(str(tmp_path)).create("CAS 命中", session_id=OWNER)
    res = run_checkpoint_goal(
        None, _host(tmp_path), {"goal_id": g.id, "what": "带版本写入", "expected_version": 1}
    )
    assert res.status == ToolResultStatus.SUCCESS
    assert GoalStore(str(tmp_path)).get(g.id)["version"] == 2


def test_stale_version_rejected(tmp_path):
    store = GoalStore(str(tmp_path))
    g = store.create("CAS 冲突", session_id=OWNER)
    store.checkpoint(g.id, what="他人已推进")  # version -> 2

    res = run_update_goal(
        None,
        _host(tmp_path),
        {"goal_id": g.id, "status": "blocked", "reason": "并发覆盖尝试", "expected_version": 1},
    )
    assert res.status == ToolResultStatus.FAILURE
    assert "reason_code=version_conflict" in res.content
    assert "current_version=2" in res.content
    after = GoalStore(str(tmp_path)).get(g.id)
    assert after["status"] == "active"
    assert after["version"] == 2


def test_invalid_expected_version_rejected(tmp_path):
    g = GoalStore(str(tmp_path)).create("非法版本", session_id=OWNER)
    res = run_checkpoint_goal(
        None, _host(tmp_path), {"goal_id": g.id, "what": "x", "expected_version": "abc"}
    )
    assert res.status == ToolResultStatus.FAILURE
    assert "expected_version" in res.content


def test_legacy_record_without_version_reads_as_one(tmp_path):
    store = GoalStore(str(tmp_path))
    legacy = {
        "id": "GOAL-LEGACY-0001",
        "objective": "旧记录",
        "status": "active",
        "created_at": "2026-01-01T00:00:00+08:00",
        "updated_at": "2026-01-01T00:00:00+08:00",
        "session_id": OWNER,
        "checkpoints": [],
    }
    path = tmp_path / "goals.jsonl"
    path.write_text(json.dumps(legacy, ensure_ascii=False) + "\n", encoding="utf-8")

    got = store.get("GOAL-LEGACY-0001")
    assert "version" not in got
    assert GoalStore.version_of(got) == 1
    res = run_checkpoint_goal(
        None, _host(tmp_path), {"goal_id": "GOAL-LEGACY-0001", "what": "旧记录首写", "expected_version": 1}
    )
    assert res.status == ToolResultStatus.SUCCESS
    assert GoalStore(str(tmp_path)).get("GOAL-LEGACY-0001")["version"] == 2
