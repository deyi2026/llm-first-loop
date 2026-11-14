"""lane_reap（P2）单元测试：超时≠死亡、三判据、三态输出、dry_run 零写。"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

from llm_loop.introspection.lane import LaneStore
from llm_loop.introspection.tools_lane import run_lane_reap

NOW = "2026-11-14T15:00:00+08:00"
OLD = "2026-11-01T00:00:00+08:00"


def _entry(lane_id, *, status="verifying", owner="sess-x", worktree="/tmp/wt", last=OLD):
    return {
        "lane_id": lane_id,
        "branch": "b/" + lane_id,
        "worktree": worktree,
        "base_main_sha": "0" * 40,
        "goal_id": "G-1",
        "owner_session_id": owner,
        "lane_role": "main",
        "paths": [],
        "contract_changes": [],
        "status": status,
        "head_sha": "",
        "priority": "normal",
        "base_is_broken": False,
        "verify_ref": "",
        "close_reason": "",
        "closing_since": "",
        "version": 1,
        "created_at": OLD,
        "last_activity": last,
    }


def _store(tmp_path, entries):
    audit = tmp_path / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    path = audit / "lanes.jsonl"
    path.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8"
    )
    return LaneStore(str(audit)), path


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _msg(res):
    for attr in ("message", "text", "content", "summary"):
        value = getattr(res, attr, None)
        if isinstance(value, str) and value:
            return value
    return str(res)


def test_no_probe_is_unavailable(tmp_path):
    store, _ = _store(tmp_path, [_entry("lane-a")])
    out = store.reap_candidates(ttl_hours=24, now=NOW)
    assert out["liveness_available"] is False
    assert out["counts"]["conclusive"] == 0
    assert out["candidates"][0]["verdict"] == "unavailable"


def test_dead_and_clean_is_conclusive(tmp_path):
    store, _ = _store(tmp_path, [_entry("lane-a")])
    out = store.reap_candidates(
        ttl_hours=24, now=NOW, liveness_probe=lambda s: "dead", tree_probe=lambda w: "clean"
    )
    assert out["counts"]["conclusive"] == 1


def test_dirty_tree_is_suspect(tmp_path):
    store, _ = _store(tmp_path, [_entry("lane-a")])
    out = store.reap_candidates(
        ttl_hours=24, now=NOW, liveness_probe=lambda s: "dead", tree_probe=lambda w: "dirty"
    )
    assert out["counts"]["suspect"] == 1
    assert out["counts"]["conclusive"] == 0


def test_alive_is_suspect(tmp_path):
    store, _ = _store(tmp_path, [_entry("lane-a")])
    out = store.reap_candidates(
        ttl_hours=24, now=NOW, liveness_probe=lambda s: "alive", tree_probe=lambda w: "clean"
    )
    assert out["counts"]["suspect"] == 1


def test_probe_exception_is_not_death(tmp_path):
    store, _ = _store(tmp_path, [_entry("lane-a")])

    def boom(_sid):
        raise RuntimeError("no capability")

    out = store.reap_candidates(
        ttl_hours=24, now=NOW, liveness_probe=boom, tree_probe=lambda w: "clean"
    )
    assert out["candidates"][0]["liveness"] == "unknown"
    assert out["counts"]["conclusive"] == 0


def test_probe_false_is_not_death(tmp_path):
    """跨进程不可见时探针返回 False —— 那不是死亡证据。"""
    store, _ = _store(tmp_path, [_entry("lane-a")])
    out = store.reap_candidates(
        ttl_hours=24, now=NOW, liveness_probe=lambda s: False, tree_probe=lambda w: "clean"
    )
    assert out["candidates"][0]["liveness"] == "unknown"
    assert out["counts"]["conclusive"] == 0


def test_fresh_lane_not_candidate(tmp_path):
    store, _ = _store(tmp_path, [_entry("lane-a", last=NOW)])
    out = store.reap_candidates(
        ttl_hours=24, now=NOW, liveness_probe=lambda s: "dead", tree_probe=lambda w: "clean"
    )
    assert out["candidates"] == []


def test_terminal_lane_not_candidate(tmp_path):
    store, _ = _store(tmp_path, [_entry("lane-a", status="merged")])
    out = store.reap_candidates(
        ttl_hours=24, now=NOW, liveness_probe=lambda s: "dead", tree_probe=lambda w: "clean"
    )
    assert out["candidates"] == []


def test_reap_candidates_zero_write(tmp_path):
    store, path = _store(tmp_path, [_entry("lane-a")])
    before = _sha(path)
    store.reap_candidates(
        ttl_hours=24, now=NOW, liveness_probe=lambda s: "dead", tree_probe=lambda w: "clean"
    )
    assert _sha(path) == before


def test_tool_dry_run_zero_write(tmp_path):
    store, path = _store(tmp_path, [_entry("lane-a")])
    before = _sha(path)
    host = SimpleNamespace(audit_dir=str(path.parent))
    res = run_lane_reap(None, host, {"dry_run": True, "ttl_hours": 24})
    assert "dry-run" in _msg(res)
    assert _sha(path) == before
    assert not (path.parent / "lane_events.jsonl").exists()


def test_tool_without_probe_reports_unavailable(tmp_path):
    store, path = _store(tmp_path, [_entry("lane-a")])
    before = _sha(path)
    host = SimpleNamespace(audit_dir=str(path.parent))
    res = run_lane_reap(None, host, {"dry_run": False, "ttl_hours": 24})
    assert "liveness_unavailable" in _msg(res)
    assert _sha(path) == before


def test_tool_suspect_flags_without_closing(tmp_path):
    """dead + 树状态非 clean → 只标疑，状态不动。"""
    store, path = _store(tmp_path, [_entry("lane-a", worktree=str(tmp_path))])
    host = SimpleNamespace(audit_dir=str(path.parent), lane_liveness_probe=lambda s: "dead")
    res = run_lane_reap(None, host, {"dry_run": False, "ttl_hours": 24})
    assert "标疑" in _msg(res)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows[0]["status"] == "verifying"
    events = (path.parent / "lane_events.jsonl").read_text(encoding="utf-8")
    assert "lane.stale_suspected" in events


def test_tool_applied_closes_conclusive_only(tmp_path):
    """dead + clean → 收口为 abandoned（工作树回收失败只记事件，不回滚收口）。"""
    store, path = _store(tmp_path, [_entry("lane-a", worktree=str(tmp_path / "missing-wt"))])
    host = SimpleNamespace(audit_dir=str(path.parent), lane_liveness_probe=lambda s: "dead")
    res = run_lane_reap(None, host, {"dry_run": False, "ttl_hours": 24})
    msg = _msg(res)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    # worktree 不存在 → tree 探测返回 unknown → suspect，不收口
    assert rows[0]["status"] == "verifying"
    assert "标疑" in msg


def _clean_repo(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    import subprocess

    subprocess.run(["git", "init", "-q", str(wt)], check=True)
    return wt


def test_tool_closes_but_keeps_worktree_by_default(tmp_path):
    """D2：收口≠清理——默认不删目录，只给可粘贴命令。"""
    wt = _clean_repo(tmp_path)
    store, path = _store(tmp_path, [_entry("lane-a", status="active", worktree=str(wt))])
    host = SimpleNamespace(audit_dir=str(path.parent), lane_liveness_probe=lambda s: "dead")
    res = run_lane_reap(None, host, {"dry_run": False, "ttl_hours": 24})
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows[0]["status"] == "abandoned"
    assert wt.exists(), "默认不得删除工作树目录"
    assert "git worktree remove" in _msg(res)


def test_tool_remove_worktree_needs_confirm(tmp_path):
    """不可逆动作的二次确认闸。"""
    wt = _clean_repo(tmp_path)
    store, path = _store(tmp_path, [_entry("lane-a", status="active", worktree=str(wt))])
    host = SimpleNamespace(audit_dir=str(path.parent), lane_liveness_probe=lambda s: "dead")
    res = run_lane_reap(None, host, {"dry_run": False, "ttl_hours": 24, "remove_worktree": True})
    assert wt.exists(), "未确认时不得删除工作树目录"
    assert "git worktree remove" in _msg(res)


def test_tool_remove_worktree_with_confirm(tmp_path):
    """remove_worktree=true 且 confirm=true 时才尝试回收。"""
    wt = _clean_repo(tmp_path)
    store, path = _store(tmp_path, [_entry("lane-a", status="active", worktree=str(wt))])
    host = SimpleNamespace(audit_dir=str(path.parent), lane_liveness_probe=lambda s: "dead")
    res = run_lane_reap(
        None,
        host,
        {"dry_run": False, "ttl_hours": 24, "remove_worktree": True, "confirm": True},
    )
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert rows[0]["status"] == "abandoned"
    events = (path.parent / "lane_events.jsonl").read_text(encoding="utf-8")
    assert "lane.worktree_kept" in events or "已回收工作树" in _msg(res)
