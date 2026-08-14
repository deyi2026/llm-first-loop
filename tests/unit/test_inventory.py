"""单元测试: D1 存量存储盘点 run_inventory（design.md §2.4.1 / spec §5.1）.

覆盖:
- tmp_path 构造最小三套存储（含缺省字段 v3 会话/损坏文件/缺失目录）
- 规模数字如实；割裂点清单与 spec §2.2 三项一致
- 盘点后文件 mtime/内容哈希不变（只读红线）
"""

from __future__ import annotations

import hashlib
import json

from llm_loop.event_log.inventory import run_inventory


def _build_minimal(tmp_path) -> dict:
    data = tmp_path / "data"
    sessions = data / "sessions"
    sessions.mkdir(parents=True)
    # 缺省字段 v3 会话
    (sessions / "s1.json").write_text(
        json.dumps(
            {"version": 3, "session_id": "s1", "title": "t", "created_at": "2026-01-01",
             "updated_at": "2026-01-01T00:00:01", "status": "active",
             "messages": [{"role": "user", "content": "hi"}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # 损坏会话文件
    (sessions / "s2.json").write_text("{broken", encoding="utf-8")
    # archives
    archives = data / "archives"
    archives.mkdir()
    (archives / "s1.jsonl").write_text(
        json.dumps({"id": "ARC-1", "tool_call_id": "c1", "chars": 10}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    # compressed_archive
    (data / "compressed_archive" / "handoff_1").mkdir(parents=True)
    # action_trace（无 session_id 字段 —— 割裂点 A 实证）
    (data / "audit").mkdir()
    (data / "audit" / "action_trace.jsonl").write_text(
        '{"ts": "2026-01-01T00:00:00", "phase": "a", "action_type": "b", "detail": "c"}\n',
        encoding="utf-8",
    )
    return data


def test_inventory_sizes_truthful(tmp_path):
    data = _build_minimal(tmp_path)
    report = run_inventory(data)
    assert len(report.sessions) == 2  # 含损坏文件如实标注 broken
    assert report.sessions[0]["version"] == 3
    broken = [s for s in report.sessions if s.get("broken")]
    assert len(broken) == 1
    assert report.archives["file_count"] == 1
    assert report.archives["entry_count"] == 1
    assert report.compressed_archive["dir_count"] == 1
    assert report.action_trace["line_count"] == 1
    assert report.action_trace["has_session_id"] is False  # 割裂点 A 实证


def test_inventory_gaps_three_items(tmp_path):
    data = _build_minimal(tmp_path)
    report = run_inventory(data)
    points = [g["point"] for g in report.gaps]
    assert len(report.gaps) == 3
    assert any("action_trace 无 session_id" in p for p in points)
    assert any("松散关联" in p for p in points)
    assert any("无统一事件序" in p for p in points)


def test_inventory_missing_dirs_annotated(tmp_path):
    data = tmp_path / "empty_data"
    data.mkdir()
    report = run_inventory(data)
    assert report.dirs_missing
    assert "sessions" in report.dirs_missing
    assert report.sessions == []
    # 缺失目录如实标注、不伪造规模（archives 未盘点保持空）
    assert report.archives == {}
    assert "archives" in report.dirs_missing
    assert "audit/action_trace.jsonl" in report.dirs_missing


def test_inventory_readonly_untouched(tmp_path):
    data = _build_minimal(tmp_path)
    snapshots = {}
    for p in data.rglob("*"):
        if p.is_file():
            snapshots[str(p)] = (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    run_inventory(data)
    for p in data.rglob("*"):
        if p.is_file():
            mtime, digest = snapshots[str(p)]
            assert p.stat().st_mtime_ns == mtime
            assert hashlib.sha256(p.read_bytes()).hexdigest() == digest
