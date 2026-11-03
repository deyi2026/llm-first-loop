"""DESIGN-20261103 N1 T-0.4b: coordination_status 的 recent_events 段接线.

覆盖:
- 流表与 RecordSearcher._EVENT_STREAMS 防漂移（文件名/摘要键同一真值）
- 时间窗口语义：窗口内进回执、窗口外丢弃、旧→新排序、他人 sid 脱敏
- 双界截断自证：top-N 截断与字节上限触顶都必须标 truncated + degraded
- 倒扫不得全文件扫描（以 _entry_ts 调用数为机械判据，不看墙钟）
- 无时间戳记录只计数不猜时间；audit_dir 不可读如实降级
- 账本崩了不连坐事件段（两段事实源互相独立）
"""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from llm_loop.core.run_context import current_session_id as _sid
from llm_loop.introspection import goal_coordination as gc
from llm_loop.introspection.goal_coordination import coordination_snapshot, render_coordination
from llm_loop.introspection.search import RecordSearcher
from llm_loop.introspection.tools_goal import run_coordination_status
from llm_loop.timekeeping import system_local_now

SELF = "sess-self-events"
OTHER = "sess-other-events-长id"


@pytest.fixture(autouse=True)
def _bind():
    token = _sid.set(SELF)
    yield
    _sid.reset(token)


def _ts(offset_s: float) -> str:
    return (system_local_now() - timedelta(seconds=offset_s)).isoformat()


def _trace(offset_s: float, *, sid: str | None = SELF, detail: str = "execute_command"):
    row = {
        "ts": _ts(offset_s),
        "phase": "action.tool_loop",
        "action_type": "tool_call",
        "detail": detail,
    }
    if sid is not None:
        row["session_id"] = sid
    return row


def _write(tmp_path, name: str, rows: list[dict]) -> None:
    with (tmp_path / name).open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _snapshot(tmp_path, **kw):
    return coordination_snapshot(str(tmp_path), window_hours=0, **kw)


def _notes(snap: dict) -> list[str]:
    return [n for n in snap.get("degraded") or [] if n.startswith("recent_events")]


def test_stream_map_matches_search_registry():
    """本地流表是 search._EVENT_STREAMS 的子集投影；两边漂移即失败."""
    registry = RecordSearcher._EVENT_STREAMS
    for name, fname, keys in gc._RECENT_EVENT_STREAMS:
        assert name in registry, name
        assert registry[name][0] == fname
        assert set(keys) <= set(registry[name][1])


def test_window_orders_masks_and_flags_mine(tmp_path):
    _write(
        tmp_path,
        "action_trace.jsonl",
        [
            _trace(600, sid=OTHER, detail="oldest"),
            _trace(120, sid=SELF, detail="middle"),
            _trace(30, sid=OTHER, detail="newest"),
        ],
    )
    snap = _snapshot(tmp_path)
    events = snap["recent_events"]
    assert snap["recent_events_total"] == 3
    assert [e["summary"] for e in events] == [
        "tool_call oldest",
        "tool_call middle",
        "tool_call newest",
    ]
    assert [e["is_mine"] for e in events] == [False, True, False]
    # 旧→新（与 event_stream 同口径），不是最新在前
    assert events[0]["ts"] < events[-1]["ts"]
    # 他人 sid 脱敏，本会话不被误标成他人
    assert events[0]["session_id"] == OTHER[:8] + "…"
    assert snap["recent_events_truncated"] is False
    assert snap["recent_events_scope"] == "workspace"
    assert 590 <= snap["recent_events_coverage_s"] <= 620
    assert _notes(snap) == []


def test_out_of_window_events_excluded(tmp_path):
    _write(tmp_path, "action_trace.jsonl", [_trace(3600, detail="too-old")])
    snap = _snapshot(tmp_path)
    assert snap["recent_events"] == []
    assert snap["recent_events_total"] == 0
    assert snap["recent_events_coverage_s"] is None


def test_top_n_truncation_marks_truncated(tmp_path):
    _write(
        tmp_path,
        "action_trace.jsonl",
        [_trace(200 - i, detail=f"hit-{i:02d}") for i in range(15)],
    )
    snap = _snapshot(tmp_path)
    assert snap["recent_events_total"] == 15
    assert len(snap["recent_events"]) == gc._EVENTS_TOP_N
    assert snap["recent_events_truncated"] is True
    # top-N 取最近 N 条：最老的 hit-00 不进回执
    summaries = [e["summary"] for e in snap["recent_events"]]
    assert "hit-00" not in summaries
    assert any("呈现最近 10/15" in n for n in _notes(snap))


def test_byte_cap_hit_marks_truncated_and_drops_half_line(tmp_path, monkeypatch):
    _write(
        tmp_path,
        "action_trace.jsonl",
        [_trace(300, detail=f"row-{i:03d}") for i in range(60)],
    )
    monkeypatch.setattr(gc, "_EVENTS_MAX_BYTES", 512)
    snap = _snapshot(tmp_path)
    notes = _notes(snap)
    assert snap["recent_events_truncated"] is True
    assert any("尾部 512B 内未回溯到 1800s 前" in n for n in notes)
    assert snap["recent_events_scanned_bytes"] == 512
    # 窗口内命中必然少于全量（只读了尾部），但那一条半行 JSON 不得进回执
    assert 0 < snap["recent_events_total"] < 60
    assert all(
        e["summary"].startswith("tool_call row-") for e in snap["recent_events"]
    )


def test_scan_stops_at_cutoff_not_file_start(tmp_path, monkeypatch):
    """倒扫在 cutoff 处停：旧记录再多也不逐个解析（不然等于全文件扫描）."""
    rows = [_trace(7200 + i, detail=f"old-{i}") for i in range(2000)]
    rows += [_trace(60 - i, detail=f"new-{i}") for i in range(3)]
    _write(tmp_path, "action_trace.jsonl", rows)
    calls = {"n": 0}
    real = gc._entry_ts

    def _counting(entry):
        calls["n"] += 1
        return real(entry)

    monkeypatch.setattr(gc, "_entry_ts", _counting)
    snap = _snapshot(tmp_path)
    assert snap["recent_events_total"] == 3
    # 3 条窗口内 + 1 条触发 cutoff 的边界行；2000 条旧记录不得被解析
    assert calls["n"] <= 4
    assert snap["recent_events_truncated"] is False


def test_unstamped_rows_counted_not_guessed(tmp_path):
    _write(
        tmp_path,
        "exception_log.jsonl",
        [{"phase": "x", "error_type": "E", "detail": "no-ts"}],
    )
    _write(tmp_path, "action_trace.jsonl", [_trace(10)])
    snap = _snapshot(tmp_path)
    assert snap["recent_events_total"] == 1
    assert any("1 条记录无可用时间戳" in n for n in _notes(snap))


def test_missing_audit_dir_is_degraded(tmp_path):
    missing = tmp_path / "nope"
    snap = coordination_snapshot(str(missing), window_hours=0)
    assert snap["recent_events"] == []
    assert any("audit_dir 不可读" in n for n in _notes(snap))


def test_zero_events_is_not_degraded(tmp_path):
    """N1-A2：空即空，不编造 degraded 噪声（只在真读不到时降级）."""
    snap = _snapshot(tmp_path)
    assert snap["recent_events_total"] == 0
    assert _notes(snap) == []


def test_ledger_failure_keeps_events_block(tmp_path, monkeypatch):
    _write(tmp_path, "action_trace.jsonl", [_trace(20, detail="survives")])
    from llm_loop.introspection.goal import GoalStore

    def _boom(self):
        raise RuntimeError("ledger corrupt")

    monkeypatch.setattr(GoalStore, "count", _boom)
    snap = _snapshot(tmp_path)
    assert snap["ok"] is False
    assert snap["recent_events_total"] == 1
    assert any("goal 账本不可读" in n for n in snap["degraded"])


def test_render_shows_events_line(tmp_path):
    _write(tmp_path, "action_trace.jsonl", [_trace(20, sid=OTHER, detail="pytest -q")])
    host = SimpleNamespace(
        audit_dir=str(tmp_path),
        ctx=SimpleNamespace(subagent_runner=None, job_registry=None),
    )
    res = run_coordination_status(None, host, {"window_hours": 0})
    assert res.status.value == "success"
    assert "events 1/1 window=1800s" in res.content
    assert "scope=workspace" in res.content
    assert OTHER[:8] + "…" in res.content
    assert OTHER not in res.content


def test_render_omits_events_when_block_absent():
    """render 兼容旧快照（没有 events 字段时不凭空造行）."""
    text = render_coordination({"ok": True, "window_hours": 0, "goals": []})
    assert "events " not in text
