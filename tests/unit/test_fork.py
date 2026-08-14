"""D3 会话 fork 事件行为测试（spec §5.1 / design.md §2.2.2-A）.

全走 tmp_path + monkeypatch DATA_DIR（M64 防污染真实 data/）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.event_log.fork import fork_session
from llm_loop.event_log.replay import replay_session
from llm_loop.event_log.store import EventStore


def _build_stores(tmp_path: Path) -> tuple[EventStore, SessionStore]:
    """构造测试用 EventStore + SessionStore（共享同一 event_logs_dir）."""
    event_logs_dir = tmp_path / "event_logs"
    sessions_dir = tmp_path / "sessions"
    event_store = EventStore(event_logs_dir, enabled=True)
    session_store = SessionStore(sessions_dir, event_store=event_store)
    return event_store, session_store


def _build_source_session(
    session_store: SessionStore, messages: list[Message]
) -> str:
    """构造源会话（含 session JSON + 事件日志双轨）."""
    sid = session_store.create()
    for msg in messages:
        session_store.append(sid, msg)
    return sid


def _user_msg(content: str) -> Message:
    return Message(role="user", content=content, source=MessageSource.USER)


def _assistant_msg(content: str) -> Message:
    return Message(role="assistant", content=content, source=MessageSource.SYSTEM)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── 正常 fork ──


def test_fork_basic(tmp_path):
    """fork 基本流程：新会话 replay 视图截至 fork 点消息与源逐字段一致."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(
        session_store,
        [_user_msg("hello"), _assistant_msg("hi"), _user_msg("world")],
    )
    report = fork_session(event_store, session_store, sid, fork_point=2)
    assert report.success, report.error
    # 新会话事件日志存在
    assert event_store.exists(report.new_session_id)
    new_events = event_store.read(report.new_session_id)
    # 首事件为 session.created（物理复制的源 session.created）
    assert new_events[0].type == "session.created"
    # replay 视图
    view = replay_session(new_events)
    assert "exists" not in view  # 有事件 → 不含 exists=False 标记
    # 截至 fork 点 2 条消息
    assert len(view["messages"]) == 2
    assert view["messages"][0]["content"] == "hello"
    assert view["messages"][1]["content"] == "hi"


def test_fork_none_point_inherits_all(tmp_path):
    """fork_point=None → 继承全部消息."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(
        session_store,
        [_user_msg("a"), _assistant_msg("b"), _user_msg("c")],
    )
    report = fork_session(event_store, session_store, sid, fork_point=None)
    assert report.success, report.error
    view = replay_session(event_store.read(report.new_session_id))
    assert len(view["messages"]) == 3


def test_fork_zero_point(tmp_path):
    """fork_point=0 → 保留 0 条消息（仅 session.created 等非消息事件）."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(
        session_store,
        [_user_msg("a"), _assistant_msg("b")],
    )
    report = fork_session(event_store, session_store, sid, fork_point=0)
    assert report.success, report.error
    view = replay_session(event_store.read(report.new_session_id))
    assert len(view["messages"]) == 0


def test_forked_event_carries_meta(tmp_path):
    """新会话含 session.forked 事件承载 fork 元信息（spec §6.1）."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(
        session_store,
        [_user_msg("hello"), _assistant_msg("world")],
    )
    report = fork_session(event_store, session_store, sid, fork_point=1)
    assert report.success
    new_events = event_store.read(report.new_session_id)
    forked_events = [e for e in new_events if e.type == "session.forked"]
    assert len(forked_events) == 1
    payload = forked_events[0].payload
    assert payload["source_session_id"] == sid
    assert payload["fork_point"] == 1
    assert payload["inherited_event_count"] == report.inherited_event_count
    assert payload["new_session_id"] == report.new_session_id
    assert "fork_ts" in payload


def test_fork_meta_in_replay_view(tmp_path):
    """replay 视图含 fork_meta 标注字段."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(session_store, [_user_msg("hello")])
    report = fork_session(event_store, session_store, sid, fork_point=1)
    view = replay_session(event_store.read(report.new_session_id))
    assert "fork_meta" in view
    assert view["fork_meta"]["source_session_id"] == sid


def test_source_unchanged(tmp_path):
    """源会话事件文件 mtime/内容哈希逐字节不变（spec §5.1.1-5）."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(
        session_store,
        [_user_msg("a"), _assistant_msg("b"), _user_msg("c")],
    )
    src_path = event_store._path(sid)  # noqa: SLF001
    src_hash_before = _file_hash(src_path)
    src_mtime_before = src_path.stat().st_mtime_ns
    fork_session(event_store, session_store, sid, fork_point=2)
    assert _file_hash(src_path) == src_hash_before
    assert src_path.stat().st_mtime_ns == src_mtime_before


def test_new_session_fields(tmp_path):
    """新会话 parent_id 指向源会话、branch_id 为自身（spec §5.1.1-3）."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(session_store, [_user_msg("hello")])
    report = fork_session(event_store, session_store, sid)
    assert report.success
    view = replay_session(event_store.read(report.new_session_id))
    assert view["parent_id"] == sid
    assert view["branch_id"] == report.new_session_id


def test_physical_copy_independent(tmp_path):
    """fork 后删除源会话事件日志 → 新会话仍可完整 replay（spec §5.1.1-7）."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(
        session_store,
        [_user_msg("a"), _assistant_msg("b")],
    )
    report = fork_session(event_store, session_store, sid, fork_point=2)
    # 删除源会话事件日志
    event_store._path(sid).unlink()  # noqa: SLF001
    # 新会话仍可 replay
    new_events = event_store.read(report.new_session_id)
    view = replay_session(new_events)
    assert len(view["messages"]) == 2
    assert view["messages"][0]["content"] == "a"


def test_new_session_seq_from_one(tmp_path):
    """新会话事件 seq 从 1 递增不重号."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(
        session_store,
        [_user_msg("a"), _assistant_msg("b")],
    )
    report = fork_session(event_store, session_store, sid, fork_point=1)
    new_events = event_store.read(report.new_session_id)
    seqs = [e.seq for e in new_events]
    assert seqs == list(range(1, len(seqs) + 1))


def test_read_path_compat(tmp_path):
    """fork 后通过 SessionStore.load 加载新会话 → 消息序列与重放视图一致（spec §5.1.1-6）."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(
        session_store,
        [_user_msg("hello"), _assistant_msg("world"), _user_msg("foo")],
    )
    report = fork_session(event_store, session_store, sid, fork_point=2)
    # 通过 SessionStore.load 加载新会话
    new_session = session_store.load(report.new_session_id)
    assert len(new_session.messages) == 2
    assert new_session.messages[0].content == "hello"
    assert new_session.messages[1].content == "world"
    assert new_session.parent_id == sid


# ── 异常场景 ──


def test_source_not_exist(tmp_path):
    """源会话事件日志不存在 → success=False + error 标注（spec §5.1.3-1）."""
    event_store, session_store = _build_stores(tmp_path)
    report = fork_session(event_store, session_store, "nonexistent-sid")
    assert not report.success
    assert "不存在" in report.error or "为空" in report.error


def test_fork_point_negative(tmp_path):
    """fork 点负数 → success=False + 合法范围标注（spec §5.1.3-2）."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(session_store, [_user_msg("a")])
    report = fork_session(event_store, session_store, sid, fork_point=-1)
    assert not report.success
    assert "越界" in report.error


def test_fork_point_too_large(tmp_path):
    """fork 点超消息数 → success=False + 合法范围标注（spec §5.1.3-2）."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(session_store, [_user_msg("a"), _assistant_msg("b")])
    report = fork_session(event_store, session_store, sid, fork_point=3)
    assert not report.success
    assert "越界" in report.error


def test_fork_point_equal_msg_count(tmp_path):
    """fork_point == msg_count → 合法（等价于继承全部）."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(session_store, [_user_msg("a"), _assistant_msg("b")])
    report = fork_session(event_store, session_store, sid, fork_point=2)
    assert report.success
    view = replay_session(event_store.read(report.new_session_id))
    assert len(view["messages"]) == 2


# ── event_store 不可用 ──


def test_event_store_disabled(tmp_path):
    """event_store 禁用 → 仅生成 session JSON（零回归）."""
    event_logs_dir = tmp_path / "event_logs"
    sessions_dir = tmp_path / "sessions"
    disabled_store = EventStore(event_logs_dir, enabled=False)
    session_store = SessionStore(sessions_dir, event_store=disabled_store)
    sid = _build_source_session(session_store, [_user_msg("a"), _assistant_msg("b")])
    report = fork_session(disabled_store, session_store, sid, fork_point=1)
    assert report.success
    # session JSON 已生成
    new_session = session_store.load(report.new_session_id)
    assert len(new_session.messages) == 1
    # 事件日志未生成（禁用）
    assert not disabled_store.exists(report.new_session_id)


def test_event_store_none(tmp_path):
    """event_store=None → 仅生成 session JSON（零回归）."""
    sessions_dir = tmp_path / "sessions"
    session_store = SessionStore(sessions_dir, event_store=None)
    sid = _build_source_session(session_store, [_user_msg("a")])
    report = fork_session(None, session_store, sid)
    assert report.success
    new_session = session_store.load(report.new_session_id)
    assert len(new_session.messages) == 1


# ── SessionStore.fork 集成 ──


def test_session_store_fork_integration(tmp_path):
    """SessionStore.fork 调 fork_session 编排，返回新 session_id."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(
        session_store,
        [_user_msg("hello"), _assistant_msg("world")],
    )
    new_id = session_store.fork(sid, branch_point_index=1)
    assert new_id != sid
    new_session = session_store.load(new_id)
    assert len(new_session.messages) == 1
    assert new_session.parent_id == sid


def test_session_store_fork_out_of_range_raises(tmp_path):
    """SessionStore.fork 越界 → 抛 ValueError（从"钳位"改为"报错"）."""
    event_store, session_store = _build_stores(tmp_path)
    sid = _build_source_session(session_store, [_user_msg("a")])
    with pytest.raises(ValueError, match="越界"):
        session_store.fork(sid, branch_point_index=5)
