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


# ── EVO-20260810-3188682f: 会话分支 ──
def test_session_fork_basic(tmp_path):
    """分支基本行为：默认末尾分叉（克隆父全部消息）+ 父引用 + 新 session_id（旧会话不覆盖）."""
    store = _store(tmp_path)
    sid = store.create()
    store.append(sid, _msg("问题A"))
    sess = store.load(sid)
    sess.messages.append(Message(role="assistant", content="方案A：改代码", source=MessageSource.USER))
    store.save(sess)

    new_id = store.fork(sid)
    assert new_id != sid
    child = store.load(new_id)
    assert child.parent_id == sid  # 父引用
    assert child.branch_id  # 分支标识生成
    assert len(child.messages) == 2  # 默认末尾分叉：拷贝父全部消息（克隆当前状态）
    # 默认末尾分叉 → 分叉点后无内容 → 摘要为空（语义：克隆当前状态继续探索）
    assert child.branch_summary == ""
    # 父会话未被覆盖（仍存在且消息不变）
    parent = store.load(sid)
    assert len(parent.messages) == 2


def test_session_fork_with_summary(tmp_path):
    """从中间分叉：新分支保留分叉点前消息，分支摘要携带分叉点后的旧结论（跨分支情报传递）."""
    store = _store(tmp_path)
    sid = store.create()
    store.append(sid, _msg("问题A"))
    sess = store.load(sid)
    sess.messages.append(Message(role="assistant", content="方案A：改代码", source=MessageSource.USER))
    sess.messages.append(Message(role="user", content="继续探索方案B", source=MessageSource.USER))
    store.save(sess)
    # 从索引 1 分叉（分叉点后 = assistant 方案A + user 继续B）
    new_id = store.fork(sid, branch_point_index=1)
    child = store.load(new_id)
    assert len(child.messages) == 1
    assert child.messages[0].content == "问题A"
    assert "方案A" in child.branch_summary  # 分叉点后最近 assistant = 方案A（旧结论携带）


def test_session_fork_at_point(tmp_path):
    """指定分叉点：新分支仅保留分叉点前消息；分叉点后无 assistant → 空摘要."""
    store = _store(tmp_path)
    sid = store.create()
    store.append(sid, _msg("消息1"))
    store.append(sid, _msg("消息2"))
    store.append(sid, _msg("消息3"))
    new_id = store.fork(sid, branch_point_index=1)
    child = store.load(new_id)
    assert len(child.messages) == 1
    assert child.messages[0].content == "消息1"
    assert child.branch_summary == ""


def test_session_fork_backward_compat(tmp_path):
    """version 2 旧文件加载：分支字段缺省（向后兼容，P0 数据零破坏）."""
    store = _store(tmp_path)
    sid = "old-v2"
    (tmp_path / "sessions" / f"{sid}.json").write_text(
        json.dumps({"version": 2, "session_id": sid, "created_at": "t0", "messages": []}),
        encoding="utf-8",
    )
    sess = store.load(sid)
    assert sess.parent_id is None
    assert sess.branch_id == ""
    assert sess.branch_summary == ""


def test_session_branches_list(tmp_path):
    """branches() 列出父会话的全部分支（不含父自身）."""
    store = _store(tmp_path)
    sid = store.create()
    b1 = store.fork(sid)
    b2 = store.fork(sid)
    ids = {b.session_id for b in store.branches(sid)}
    assert b1 in ids and b2 in ids
    assert sid not in ids


# ── 管理完善（EVO-20260811）: save 统一维护 title/updated_at + rename ──
def test_save_updates_updated_at(tmp_path):
    """save() 更新 updated_at（修复：LoopEngine.run 走 save 时间不动）."""
    store = _store(tmp_path)
    sid = store.create()
    first = store.get_meta(sid)
    # 模拟时间流逝后保存
    import time
    time.sleep(0.02)
    sess = store.load(sid)
    sess.messages.append(Message(role="user", content="新消息", source=MessageSource.USER))
    store.save(sess)
    after = store.get_meta(sid)
    assert after.updated_at > first.updated_at  # 时间更新了


def test_save_generates_title_when_empty(tmp_path):
    """save() 补 title（修复：run 走 save 不生成标题 → 全未命名）."""
    store = _store(tmp_path)
    sid = store.create()
    sess = store.load(sid)
    sess.messages.append(Message(role="user", content="这是首条用户消息", source=MessageSource.USER))
    store.save(sess)
    assert store.load(sid).title == "这是首条用户消息"[:30]


def test_save_keeps_existing_title(tmp_path):
    """已有标题不被覆盖（幂等）."""
    store = _store(tmp_path)
    sid = store.create()
    store.append(sid, _msg("首条"))
    sess = store.load(sid)
    sess.title = "手动标题"
    store.save(sess)
    assert store.load(sid).title == "手动标题"


def test_rename_session(tmp_path):
    """rename(): 重命名成功 / 不存在返回 False / 空标题返回 False."""
    store = _store(tmp_path)
    sid = store.create()
    assert store.rename(sid, "我的会话") is True
    assert store.load(sid).title == "我的会话"
    assert store.rename("no-such", "x") is False
    assert store.rename(sid, "   ") is False  # 空标题


# ── 跨端共享当前会话（Web/飞书同一上下文）──
def test_shared_current_roundtrip(tmp_path):
    """set/get 共享当前会话（Web/飞书对称复用，fail-open）."""
    store = _store(tmp_path)
    assert store.get_shared_current() is None  # 初始无共享
    sid = store.create()
    store.set_shared_current(sid)
    assert store.get_shared_current() == sid


def test_shared_current_ignores_deleted_session(tmp_path):
    """共享当前指向已删除会话 → 返回 None（下次新建）."""
    store = _store(tmp_path)
    sid = store.create()
    store.set_shared_current(sid)
    store.delete(sid)
    assert store.get_shared_current() is None


def test_shared_current_corrupt_file_fail_open(tmp_path):
    """共享文件损坏 → get 返回 None（fail-open，不阻断）."""
    store = _store(tmp_path)
    p = tmp_path / "sessions" / "shared_current_session.json"
    p.write_text("{broken", encoding="utf-8")
    assert store.get_shared_current() is None


def test_shared_current_isolated_by_workspace(tmp_path):
    """工作区管理：共享当前会话按工作区分区，互不串扰."""
    store = _store(tmp_path)
    sid_a = store.create()
    store.set_shared_current(sid_a)
    assert store.get_shared_current() == sid_a
    # 切工作区 B → 无共享
    store.set_root(tmp_path / "sessions" / "ws_b")
    assert store.get_shared_current() is None
    sid_b = store.create()
    store.set_shared_current(sid_b)
    assert store.get_shared_current() == sid_b
    # 切回 A → A 的共享未受影响
    store.set_root(tmp_path / "sessions")
    assert store.get_shared_current() == sid_a


def test_session_corrupt_file_backed_up(tmp_path):
    """会话文件损坏 → load 备份为 .corrupt.json（不直接覆盖丢数据）+ 返回空会话."""
    store = _store(tmp_path)
    sid = "corrupt-session"
    p = store._path(sid)  # noqa: SLF001 — 测试直写存储层
    p.write_text("{broken json!!", encoding="utf-8")
    sess = store.load(sid)
    assert sess.session_id == sid  # fail-open 返回空会话
    backup = tmp_path / "sessions" / "corrupt-session.corrupt.json"
    assert backup.exists()  # 原始损坏已备份
    assert "{broken json!!" in backup.read_text(encoding="utf-8")  # 备份保留原始内容


# ── M52-fix: create(model_override=...) /new·/clear 新建继承模型覆盖 ──
def test_create_with_model_override_persisted(tmp_path):
    """M52-fix: create 带 model_override 持久化，load 后保持（/new 继承用）."""
    store = _store(tmp_path)
    sid = store.create(model_override="kimi/k3-256k")
    assert store.load(sid).model_override == "kimi/k3-256k"


def test_create_default_model_override_none(tmp_path):
    """向后兼容：无参 create 的 model_override 为 None（回落装配默认）."""
    store = _store(tmp_path)
    sid = store.create()
    assert store.load(sid).model_override is None
