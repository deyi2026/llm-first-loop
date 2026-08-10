"""单元测试: 多会话管理（T24-T26 / FR-P1-SES 系列）."""

from __future__ import annotations

import json

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore, _make_title


def _store(tmp_path) -> SessionStore:
    return SessionStore(tmp_path / "sessions")


def _msg(content: str) -> Message:
    return Message(role="user", content=content, source=MessageSource.USER)


# ── T24: SessionMeta + 元数据 ──
def test_session_meta_construction():
    from llm_loop.core.session import SessionMeta

    m = SessionMeta(
        session_id="s1",
        title="标题",
        created_at="t1",
        updated_at="t2",
        message_count=3,
        status="active",
        last_message_preview="预览",
    )
    d = m.to_dict()
    assert d["session_id"] == "s1"
    assert d["status"] == "active"


def test_version1_old_file_backward_compat(tmp_path):
    """version 1 旧文件读取自动补默认字段（向后兼容，P0 数据零破坏）."""
    store = _store(tmp_path)
    sid = "old-session-1"
    (tmp_path / "sessions" / f"{sid}.json").write_text(
        json.dumps({"version": 1, "session_id": sid, "created_at": "t0", "messages": []}),
        encoding="utf-8",
    )
    session = store.load(sid)
    assert session.title == ""  # 补默认
    assert session.status == "active"
    assert session.updated_at  # 补默认


def test_title_generated_once(tmp_path):
    """标题仅首条用户消息生成一次."""
    store = _store(tmp_path)
    sid = store.create()
    store.append(sid, _msg("这是第一条用户消息，用来生成标题内容"))
    store.append(sid, _msg("第二条消息"))
    session = store.load(sid)
    assert session.title == "这是第一条用户消息，用来生成标题内容"[:30]
    assert len(session.title) <= 30


def test_append_updates_metadata(tmp_path):
    """append 后 updated_at/message_count 刷新（FR-P1-SES-02）."""
    store = _store(tmp_path)
    sid = store.create()
    store.append(sid, _msg("你好"))
    meta = store.get_meta(sid)
    assert meta is not None
    assert meta.message_count == 1


def test_make_title_deterministic():
    assert _make_title("  你好世界  ") == "你好世界"
    assert _make_title("   ") == ""


# ── T25: 多会话方法 ──
def test_list_sessions_sorted_and_archived_filter(tmp_path):
    store = _store(tmp_path)
    a = store.create()
    b = store.create()
    store.append(b, _msg("B 会话"))
    store.append(a, _msg("A 会话"))
    metas = store.list_sessions()
    assert len(metas) == 2
    assert metas[0].session_id == a  # 最新更新在前
    # 归档隐藏
    store.archive(a)
    metas_active = store.list_sessions()
    assert len(metas_active) == 1
    metas_all = store.list_sessions(include_archived=True)
    assert len(metas_all) == 2


def test_search_title_and_content(tmp_path):
    store = _store(tmp_path)
    sid = store.create()
    store.append(sid, _msg("处理数据分析报告"))
    # 标题命中
    hits = store.search("数据分析")
    assert len(hits) >= 1
    assert hits[0]["location"] == "标题"
    # 内容命中（标题与内容关键词不重叠: 内容含"特别内容XYZ"）
    sid2 = store.create()
    store.append(sid2, _msg("A 完全无关的开头"))
    store.append(sid2, _msg("这里提到特别内容XYZ"))
    hits2 = store.search("特别内容XYZ")
    assert len(hits2) == 1
    assert "消息#" in hits2[0]["location"]


def test_search_no_hit(tmp_path):
    store = _store(tmp_path)
    store.create()
    assert store.search("完全不存在的东西xyz") == []


def test_archive_content_retained(tmp_path):
    """归档后内容仍可 load（FR-P1-SES-04）."""
    store = _store(tmp_path)
    sid = store.create()
    store.append(sid, _msg("归档前的内容"))
    assert store.archive(sid)
    session = store.load(sid)
    assert session.status == "archived"
    assert len(session.messages) == 1
    # 取消归档
    assert store.unarchive(sid)
    assert store.load(sid).status == "active"


def test_delete_physical_and_missing(tmp_path):
    """delete 物理删除 + 不存在如实处理."""
    store = _store(tmp_path)
    sid = store.create()
    assert store.delete(sid)
    assert not store.exists(sid)
    assert not store.delete("nonexistent-id")  # 不存在 → False 不伪装成功


def test_get_meta_missing(tmp_path):
    store = _store(tmp_path)
    assert store.get_meta("no-such-id") is None


def test_reasoning_content_persisted(tmp_path):
    """M20 THK-04: reasoning_content 落盘恢复保留；旧 JSON 无键 → None 向后兼容."""
    from llm_loop.core.session import Session, SessionStore, _message_from_dict

    store = SessionStore(tmp_path / "sessions")
    sid = store.create()
    sess = Session(session_id=sid)
    sess.messages.append(
        Message(
            role="assistant", content="答", source=MessageSource.USER, reasoning_content="思考链"
        )
    )
    # 落盘恢复
    store.save(sess)
    loaded = store.load(sid)
    assert loaded.messages[0].reasoning_content == "思考链"
    # 旧 JSON 无键 → None
    m = _message_from_dict({"role": "assistant", "content": "旧", "source": "user"})
    assert m.reasoning_content is None
