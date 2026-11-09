"""lane 收口治理回归（2026-11-10，收口治理③）。

背景（2026-11-09 实测反例）：queue.merged 已落账、lane 却停在 merging——
卡住所有 main push 一夜，最后靠人工代收口解锁。同时 lane_close 只有 CAS、
没有属主判定：任何会话可 close 任何 lane（治理缺口，2026-11-10 复核仍如此）。

覆盖：
1. LaneStore.close_if_live：在途 → 幂等落终态（reason 引用队列事实）；
   已终态/账本缺失 → 如实回执不抛异常；
2. lane_queue_confirm(done) → queue.merged 顺手把 lane 收敛为 merged；
3. lane_close 非属主机械授权：无可证事实 → close_not_authorized；
   「队列已 merged」/「闲置 ≥ STALE_AFTER_S」两类可证事实 → 放行。
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta
from pathlib import Path

from llm_loop.core.lane_main_write_guard import STALE_AFTER_S
from llm_loop.introspection.lane import LaneStore
from llm_loop.introspection.tools_lane import run_lane_close
from llm_loop.introspection.tools_merge_queue import run_lane_queue_confirm


class _Host:
    def __init__(self, audit_dir: Path) -> None:
        self.audit_dir = str(audit_dir)


def _mk_lane(audit: Path, *, owner: str = "sess-A", branch: str = "feat/probe") -> dict:
    store = LaneStore(str(audit))
    entry = store.create(
        branch=branch,
        worktree="/tmp/wt-probe",
        base_main_sha="1" * 40,
        goal_id="GOAL-TEST",
        owner_session_id=owner,
        lane_role="sub",
        paths=[],
        contract_changes=[],
        priority="normal",
    )
    return dataclasses.asdict(entry)


def _write_queue_row(audit: Path, lane: dict, *, status: str = "merging") -> None:
    row = {
        "queue_id": "mq-test-1",
        "lane_id": lane["lane_id"],
        "branch": lane["branch"],
        "head_sha": "2" * 40,
        "base_main_sha": lane["base_main_sha"],
        "paths": [],
        "verify_ref": "receipt-x",
        "status": status,
        "version": 1,
    }
    (audit / "merge_queue.jsonl").write_text(
        json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# ---- 1. close_if_live -------------------------------------------------------


def test_close_if_live_closes_inflight_and_is_idempotent(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    audit.mkdir()
    lane = _mk_lane(audit)
    store = LaneStore(str(audit))
    store.update(lane["lane_id"], expected_version=1, status="verifying")

    r1 = store.close_if_live(
        lane["lane_id"], status="merged",
        reason="queue.merged 自动收口（mq-test-1；merge_commit=abc）",
    )
    assert r1["closed"] is True
    row = store.get(lane["lane_id"])
    assert row is not None and row["status"] == "merged"
    assert "queue.merged" in str(row.get("close_reason") or "")

    r2 = store.close_if_live(lane["lane_id"], status="merged", reason="重复收口")
    assert r2.get("closed") is False and r2.get("already") == "merged"


def test_close_if_live_reports_missing_lane(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    audit.mkdir()
    store = LaneStore(str(audit))
    result = store.close_if_live("lane-void", status="merged", reason="孤儿队列项")
    assert result.get("closed") is False and result.get("missing") is True


# ---- 2. queue done 顺手收敛 lane --------------------------------------------


def test_queue_confirm_done_autocloses_lane(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    audit.mkdir()
    host = _Host(audit)
    lane = _mk_lane(audit)
    LaneStore(str(audit)).update(lane["lane_id"], expected_version=1, status="verifying")
    _write_queue_row(audit, lane, status="merging")

    result = run_lane_queue_confirm(None, host, {
        "action": "done",
        "lane_id": lane["lane_id"],
        "expected_version": 1,
        "merge_commit": "f" * 40,
    })
    assert result.status.value == "success", result.content
    assert "lane 已自动落终态" in result.content

    row = LaneStore(str(audit)).get(lane["lane_id"])
    assert row is not None and row["status"] == "merged"
    assert "mq-test-1" in str(row.get("close_reason") or "")


def test_queue_confirm_done_survives_missing_lane_ledger_entry(tmp_path: Path) -> None:
    """队列孤儿（账本无此 lane）：done 仍是事实，不因自动收口失败而回滚。"""
    audit = tmp_path / "audit"
    audit.mkdir()
    host = _Host(audit)
    ghost = {
        "lane_id": "lane-ghost", "branch": "feat/ghost",
        "base_main_sha": "1" * 40,
    }
    _write_queue_row(audit, ghost, status="merging")
    result = run_lane_queue_confirm(None, host, {
        "action": "done", "lane_id": "lane-ghost",
        "expected_version": 1, "merge_commit": "e" * 40,
    })
    assert result.status.value == "success", result.content


# ---- 3. lane_close 非属主机械授权 -------------------------------------------


def _patch_caller(monkeypatch, caller: str) -> None:
    from llm_loop.introspection import tools_status

    monkeypatch.setattr(tools_status, "bound_session_id", lambda: caller)


def test_close_by_non_owner_without_facts_is_denied(tmp_path: Path, monkeypatch) -> None:
    audit = tmp_path / "audit"
    audit.mkdir()
    host = _Host(audit)
    lane = _mk_lane(audit, owner="sess-A")
    _patch_caller(monkeypatch, "sess-B")

    result = run_lane_close(None, host, {
        "lane_id": lane["lane_id"], "expected_version": 1,
        "status": "abandoned", "reason": "非属主尝试关闭",
    })
    assert result.status.value == "failure"
    assert "close_not_authorized" in result.content
    row = LaneStore(str(audit)).get(lane["lane_id"])
    assert row is not None and row["status"] == "open"


def test_close_by_non_owner_allowed_when_queue_merged(tmp_path: Path, monkeypatch) -> None:
    audit = tmp_path / "audit"
    audit.mkdir()
    host = _Host(audit)
    lane = _mk_lane(audit, owner="sess-A")
    _write_queue_row(audit, lane, status="merged")
    _patch_caller(monkeypatch, "sess-B")

    result = run_lane_close(None, host, {
        "lane_id": lane["lane_id"], "expected_version": 1,
        "status": "merged", "reason": "队列已 merged，代收口（mq-test-1）",
    })
    assert result.status.value == "success", result.content


def test_close_by_non_owner_allowed_when_idle_over_stale(tmp_path: Path, monkeypatch) -> None:
    audit = tmp_path / "audit"
    audit.mkdir()
    host = _Host(audit)
    lane = _mk_lane(audit, owner="sess-A")
    # 闲置事实直接写入账本（last_activity 回拨到 STALE_AFTER_S 之前）
    stale = (datetime.now().astimezone() - timedelta(seconds=STALE_AFTER_S + 600))
    path = audit / "lanes.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    for row in rows:
        if row.get("lane_id") == lane["lane_id"]:
            row["last_activity"] = stale.isoformat()
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    _patch_caller(monkeypatch, "sess-B")

    result = run_lane_close(None, host, {
        "lane_id": lane["lane_id"], "expected_version": 1,
        "status": "abandoned",
        "reason": f"owner 失联闲置超 {STALE_AFTER_S / 3600:.0f}h，代收口",
    })
    assert result.status.value == "success", result.content


def test_close_by_owner_or_unowned_lane_not_gated(tmp_path: Path, monkeypatch) -> None:
    audit = tmp_path / "audit"
    audit.mkdir()
    host = _Host(audit)

    unowned = _mk_lane(audit, owner="", branch="feat/unowned")
    r1 = run_lane_close(None, host, {
        "lane_id": unowned["lane_id"], "expected_version": 1,
        "status": "closed", "reason": "无属主 lane，不设限",
    })
    assert r1.status.value == "success", r1.content

    owned = _mk_lane(audit, owner="sess-A", branch="feat/owned")
    _patch_caller(monkeypatch, "sess-A")
    r2 = run_lane_close(None, host, {
        "lane_id": owned["lane_id"], "expected_version": 1,
        "status": "merged", "reason": "属主本人收口",
    })
    assert r2.status.value == "success", r2.content
