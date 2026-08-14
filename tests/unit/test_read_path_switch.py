"""读路径切换测试（spec §5.2.1 / design.md §2.4.1）.

全走 tmp_path（M64 防污染真实 data/）。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.event_log.store import EventStore


def _build_stores(tmp_path: Path, read_path: str = "session_json") -> tuple[EventStore, SessionStore]:
    event_store = EventStore(tmp_path / "event_logs", enabled=True)
    session_store = SessionStore(
        tmp_path / "sessions",
        event_store=event_store,
        read_path_source=read_path,
    )
    return event_store, session_store


def _seed(session_store: SessionStore) -> str:
    sid = session_store.create()
    session_store.append(sid, Message(role="user", content="hello", source=MessageSource.USER))
    session_store.append(sid, Message(role="assistant", content="world", source=MessageSource.SYSTEM))
    return sid


def test_read_path_session_json_default(tmp_path):
    """READ_PATH_SOURCE=session_json（默认）→ 既有 load 行为（零回归）."""
    _, session_store = _build_stores(tmp_path, "session_json")
    sid = _seed(session_store)
    session = session_store.load(sid)
    assert len(session.messages) == 2
    assert session.messages[0].content == "hello"


def test_read_path_event_log_replay(tmp_path):
    """READ_PATH_SOURCE=event_log → 从事件日志 replay 重建."""
    event_store, session_store = _build_stores(tmp_path, "session_json")
    sid = _seed(session_store)
    # 切换读路径为 event_log
    session_store._read_path_source = "event_log"  # noqa: SLF001
    session = session_store.load(sid)
    assert len(session.messages) == 2
    assert session.messages[0].content == "hello"
    assert session.messages[1].content == "world"


def test_read_path_event_log_fallback_on_missing(tmp_path):
    """event_log 模式下事件日志不存在 → 回退 session JSON."""
    event_store, session_store = _build_stores(tmp_path, "session_json")
    sid = _seed(session_store)
    # 删除事件日志
    event_store._path(sid).unlink()  # noqa: SLF001
    session_store._read_path_source = "event_log"  # noqa: SLF001
    # 应回退到 session JSON
    session = session_store.load(sid)
    assert len(session.messages) == 2


def test_read_path_event_log_fallback_on_corrupt(tmp_path):
    """event_log 模式下事件日志损坏 → 回退 session JSON."""
    event_store, session_store = _build_stores(tmp_path, "session_json")
    sid = _seed(session_store)
    # 损坏事件日志
    event_store._path(sid).write_text("not json\n", encoding="utf-8")  # noqa: SLF001
    session_store._read_path_source = "event_log"  # noqa: SLF001
    session = session_store.load(sid)
    assert len(session.messages) == 2


def test_read_path_switch_reversible(tmp_path):
    """灰度切换可逆：切 event_log → 切回 session_json 行为恢复."""
    event_store, session_store = _build_stores(tmp_path, "session_json")
    sid = _seed(session_store)
    # 切 event_log
    session_store._read_path_source = "event_log"  # noqa: SLF001
    s1 = session_store.load(sid)
    assert s1.messages[0].content == "hello"
    # 切回 session_json
    session_store._read_path_source = "session_json"  # noqa: SLF001
    s2 = session_store.load(sid)
    assert s2.messages[0].content == "hello"
