"""单元测试: D1 存量迁移与回滚（design.md §2.4.1 / spec §5.5）.

覆盖:
- tmp_path 构造多会话源 → 连续迁移两次事件不重复且校验一致（幂等）
- 备份存在且与源逐字节一致
- 单会话损坏 → 该会话失败其余正常、整体不中断（fail-open）
- 回滚后源文件逐字节恢复
- 迁移不删源（迁移后源 mtime/哈希不变）
- 压缩标注消息生成 context.compressed 引用
"""

from __future__ import annotations

import hashlib
import json

from llm_loop.event_log.migrate import run_migration, run_rollback
from llm_loop.event_log.reconcile import reconcile
from llm_loop.event_log.replay import replay_session
from llm_loop.event_log.store import EventStore


def _session_dict(sid: str, with_compressed: bool = False) -> dict:
    messages = [
        {"role": "user", "content": "问题", "source": "user", "tool_call_id": None,
         "status": None, "tool_name": None, "error_detail": None, "tool_calls": None,
         "reasoning_content": None, "metadata": {}},
        {"role": "assistant", "content": "回答", "source": "user", "tool_call_id": None,
         "status": None, "tool_name": None, "error_detail": None, "tool_calls": None,
         "reasoning_content": "思考", "metadata": {}},
    ]
    if with_compressed:
        messages.append(
            {"role": "tool", "content": "…[本消息已压缩，完整内容已另存]…", "source": "tool",
             "tool_call_id": "c1", "status": "success", "tool_name": "f1",
             "error_detail": None, "tool_calls": None, "reasoning_content": None, "metadata": {}}
        )
    return {
        "version": 4, "session_id": sid, "created_at": "2026-01-01T00:00:00",
        "title": f"会话{sid}", "updated_at": "2026-01-01T00:01:00", "status": "active",
        "parent_id": None, "branch_id": "", "branch_summary": "", "model_override": None,
        "pinned": False, "channel": "web", "messages": messages,
    }


def _write_sessions(sessions_dir, specs: list[tuple[str, bool]]) -> dict[str, dict]:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    sources = {}
    for sid, comp in specs:
        d = _session_dict(sid, with_compressed=comp)
        (sessions_dir / f"{sid}.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        sources[sid] = d
    return sources


def test_migration_idempotent_no_duplicate(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    sources = _write_sessions(sessions_dir, [("s1", False), ("s2", True)])

    r1 = run_migration(sessions_dir, logs_dir)
    assert r1.sessions_total == 2
    assert r1.migrated == 2
    assert r1.failed == []

    store = EventStore(logs_dir)
    lines_after_first = len((logs_dir / "s1.jsonl").read_text(encoding="utf-8").splitlines())

    r2 = run_migration(sessions_dir, logs_dir)
    assert r2.skipped_existing == 2
    assert r2.migrated == 0
    assert len((logs_dir / "s1.jsonl").read_text(encoding="utf-8").splitlines()) == lines_after_first

    # 迁移后校验一致
    for sid, src in sources.items():
        rep = reconcile(replay_session(store.read(sid)), src)
        assert rep.passed, f"{sid} 校验不一致: {rep.top_level_diffs[:1]} {rep.message_diffs[:1]}"


def test_migration_compressed_marker_events(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    _write_sessions(sessions_dir, [("s1", True)])
    r = run_migration(sessions_dir, logs_dir)
    assert r.migrated == 1
    store = EventStore(logs_dir)
    events = store.read("s1")
    comp = [e for e in events if e.type == "context.compressed"]
    assert len(comp) == 1
    assert comp[0].payload["tool_call_id"] == "c1"
    assert comp[0].payload["msg_seq"] == 2


def test_migration_backup_byte_identical(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    _write_sessions(sessions_dir, [("s1", False), ("s2", False)])
    r = run_migration(sessions_dir, logs_dir)
    backup = __import__("pathlib").Path(r.backup_dir)
    assert backup.is_dir()
    for sid in ("s1", "s2"):
        src_bytes = (sessions_dir / f"{sid}.json").read_bytes()
        bak_bytes = (backup / "sessions" / f"{sid}.json").read_bytes()
        assert src_bytes == bak_bytes  # 备份与源逐字节一致


def test_migration_broken_session_does_not_interrupt(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    _write_sessions(sessions_dir, [("good1", False)])
    # 损坏会话
    (sessions_dir / "broken.json").write_text("{corrupt", encoding="utf-8")
    r = run_migration(sessions_dir, logs_dir)
    assert r.sessions_total == 2
    assert r.migrated == 1  # good1 迁移成功
    failed_sids = [f["session_id"] for f in r.failed]
    assert "broken" in failed_sids  # broken 如实失败
    assert not (logs_dir / "broken.jsonl").exists()


def test_rollback_restores_byte_identical(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    sources = _write_sessions(sessions_dir, [("s1", False), ("s2", False)])
    r = run_migration(sessions_dir, logs_dir)

    # 篡改源（模拟回滚前状态被改动）
    (sessions_dir / "s1.json").write_text("{}", encoding="utf-8")
    result = run_rollback(r.backup_dir, logs_dir)
    assert set(result["restored"]) == {"s1", "s2"}
    assert result["errors"] == []
    # 回滚后源逐字节恢复
    for sid, src in sources.items():
        restored = json.loads((sessions_dir / f"{sid}.json").read_text(encoding="utf-8"))
        assert restored == src


def test_rollback_remove_events(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    _write_sessions(sessions_dir, [("s1", False)])
    r = run_migration(sessions_dir, logs_dir)
    assert (logs_dir / "s1.jsonl").exists()
    result = run_rollback(r.backup_dir, logs_dir, remove_events=True)
    assert "s1" in result["events_removed"]
    assert not (logs_dir / "s1.jsonl").exists()


def test_migration_does_not_delete_source(tmp_path):
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    sources = _write_sessions(sessions_dir, [("s1", False)])
    snap = {}
    for sid in sources:
        p = sessions_dir / f"{sid}.json"
        snap[sid] = (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    run_migration(sessions_dir, logs_dir)
    for sid in sources:
        p = sessions_dir / f"{sid}.json"
        assert p.exists()  # 迁移不删源
        assert p.stat().st_mtime_ns == snap[sid][0]
        assert hashlib.sha256(p.read_bytes()).hexdigest() == snap[sid][1]


def test_migration_v3_missing_top_level_fields_defaults(tmp_path):
    """v3 旧会话缺 pinned/channel/model_override 键 → 迁移事件承载读路径默认值（spec §5.4.1-1）."""
    sessions_dir = tmp_path / "sessions"
    logs_dir = tmp_path / "event_logs"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    # v3 形态：缺 pinned/channel/model_override 键（Session.load 缺省向后兼容）
    data = _session_dict("v3s1")
    for key in ("pinned", "channel", "model_override"):
        data.pop(key, None)
    data["version"] = 3
    (sessions_dir / "v3s1.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    r = run_migration(sessions_dir, logs_dir)
    assert r.migrated == 1
    assert r.failed == []

    store = EventStore(logs_dir)
    events = store.read("v3s1")
    created = next(e for e in events if e.type == "session.created")
    # 缺省字段承载读路径语义默认值（而非 None）：与 Session.load().to_dict() 对齐
    assert created.payload.get("pinned") is False
    assert created.payload.get("channel") == "web"
    assert created.payload.get("model_override") is None
    # 重放视图 vs 源逐字段一致（读路径语义补默认后一致）
    rep = reconcile(replay_session(events), data)
    assert rep.passed, f"v3 会话校验不一致: {rep.top_level_diffs}"
