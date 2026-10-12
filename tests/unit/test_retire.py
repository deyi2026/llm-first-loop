"""三套存储退役测试（spec §5.2 / design.md §2.2.2-B）.

全走 tmp_path（M64 防污染真实 data/）。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.event_log.retire import run_retire, run_retire_rollback
from llm_loop.event_log.store import EventStore


def _build_dual_track(tmp_path: Path, num_sessions: int = 2) -> Path:
    """构造双轨数据（session JSON + 事件日志对账一致）."""
    data_dir = tmp_path / "data"
    event_store = EventStore(data_dir / "event_logs", enabled=True)
    session_store = SessionStore(data_dir / "sessions", event_store=event_store)
    for i in range(num_sessions):
        sid = session_store.create()
        session_store.append(sid, Message(role="user", content=f"msg-{i}", source=MessageSource.USER))
        session_store.append(sid, Message(role="assistant", content=f"reply-{i}", source=MessageSource.SYSTEM))
    return data_dir


def test_retire_basic(tmp_path):
    """退役基本流程：备份→对账→归档→就绪切换（P1-2：如实标注，不伪造切换事实）."""
    data_dir = _build_dual_track(tmp_path, num_sessions=2)
    report = run_retire(data_dir)
    assert report.error == "", report.error
    assert report.reconcile_passed
    assert "backup" in report.retired_steps
    assert "reconcile" in report.retired_steps
    # P1-2: 程序不替人改 .env——报告"可切换就绪" + 人工指引，而非谎称已切换
    assert report.read_path_ready_to_switch
    assert report.switch_instructions, "缺人工切换指引"
    assert any("READ_PATH_SOURCE=event_log" in s for s in report.switch_instructions)
    assert any("重启" in s for s in report.switch_instructions)
    assert "sessions" in report.archived_files


def test_retire_already_on_event_log(tmp_path):
    """P1-2: 当前读路径已是 event_log → 指引如实标注无需切换."""
    data_dir = _build_dual_track(tmp_path)
    report = run_retire(data_dir, read_path_source="event_log")
    assert report.error == ""
    assert report.read_path_ready_to_switch
    assert any("已是 event_log" in s for s in report.switch_instructions)


def test_retire_backup_created(tmp_path):
    """退役前自动备份到 _retired/_backup/<ts>/."""
    data_dir = _build_dual_track(tmp_path)
    report = run_retire(data_dir)
    assert report.backup_dir
    backup = Path(report.backup_dir)
    assert backup.exists()
    assert (backup / "sessions").exists()


def test_retire_archived_sessions(tmp_path):
    """session JSON 归档到 _retired/sessions/."""
    data_dir = _build_dual_track(tmp_path)
    report = run_retire(data_dir)
    assert report.error == ""
    archived = data_dir / "_retired" / "sessions"
    assert archived.exists()
    jsons = list(archived.glob("*.json"))
    assert len(jsons) == 2


def test_retire_rollback_restores(tmp_path):
    """回滚后源文件恢复."""
    data_dir = _build_dual_track(tmp_path)
    report = run_retire(data_dir)
    assert report.error == ""
    result = run_retire_rollback(report.backup_dir, data_dir)
    assert "sessions" in result["restored"]
    assert not result["errors"]


def test_retire_reconcile_failure(tmp_path):
    """双轨对账不一致 → 不切换不退役."""
    data_dir = _build_dual_track(tmp_path, num_sessions=1)
    # 篡改事件日志制造不一致
    event_logs = data_dir / "event_logs"
    for p in event_logs.glob("*.jsonl"):
        lines = p.read_text(encoding="utf-8").strip().split("\n")
        # 删除最后一个事件（制造消息缺失）
        p.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    report = run_retire(data_dir)
    assert not report.reconcile_passed
    assert not report.read_path_ready_to_switch
    assert "对账不一致" in report.error


def test_retire_empty_data(tmp_path):
    """空数据目录 → 退役通过（无会话可对账）."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "sessions").mkdir()
    (data_dir / "event_logs").mkdir()
    report = run_retire(data_dir)
    assert report.error == ""
    assert report.reconcile_passed
