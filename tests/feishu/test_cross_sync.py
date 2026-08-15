"""飞书 ← Web 跨端同步测试（2026-08-15 用户需求）.

真实 SessionStore/SessionMap（tmp 目录），CrossSyncWatcher 直接 poll_once 驱动，
断言：Web 侧新消息推送到映射飞书聊天；桥自身输出（mark_processed）不重复推送；
首见会话不推历史；速率受限合并；会话清理不推送；损坏会话 fail-open。
"""

from __future__ import annotations

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.feishu.cross_sync import CrossSyncWatcher, _key_target
from llm_loop.feishu.session_map import SessionMap


def _make(tmp_path, owner: str = "ou_owner"):
    store = SessionStore(str(tmp_path / "sessions"))
    smap = SessionMap(store, path=str(tmp_path / "map.json"), owner_open_id=owner)
    replies: list[tuple[str, str, str]] = []
    watcher = CrossSyncWatcher(
        store, smap, lambda rid, text, rtype: replies.append((rid, text, rtype)),
        str(tmp_path / "sessions"), poll_s=1.5, min_interval_s=3.0, max_chars=200,
    )
    return store, smap, watcher, replies


def _append_web(store: SessionStore, sid: str, texts: list[str]) -> None:
    """模拟 Web 侧写入（用户消息 + AI 回复）."""
    for i, t in enumerate(texts):
        role = "user" if i % 2 == 0 else "assistant"
        store.append(sid, Message(role=role, content=t, source=MessageSource.USER))


def test_key_target():
    assert _key_target("p:ou_x") == ("ou_x", "open_id")
    assert _key_target("g:chat_x") == ("chat_x", "chat_id")
    assert _key_target("x") is None


def test_web_new_messages_pushed_to_mapped_chat(tmp_path):
    """Web 侧增量（用户输入 + AI 输出）→ 推送到飞书映射聊天."""
    store, smap, watcher, replies = _make(tmp_path)
    sid = smap.get_or_create("p:ou_owner")  # owner 私聊（映射 + 共享当前）
    watcher.poll_once()  # 首见建基线（不推历史）
    assert replies == []
    _append_web(store, sid, ["Web 用户问题", "AI 完整回答内容"])
    watcher.poll_once()
    assert len(replies) == 1
    rid, text, rtype = replies[0]
    assert rid == "ou_owner" and rtype == "open_id"
    assert "跨端同步" in text and "Web 用户问题" in text and "AI 完整回答内容" in text
    # 无新消息 → 不重复推送
    watcher.poll_once()
    assert len(replies) == 1


def test_bridge_own_output_not_repushed(tmp_path):
    """桥自身输出（mark_processed 后）不重复推送."""
    store, smap, watcher, replies = _make(tmp_path)
    sid = smap.get_or_create("p:ou_owner")
    watcher.poll_once()
    # 模拟桥自身 run：写入并 mark_processed
    _append_web(store, sid, ["飞书用户问题", "飞书侧回复"])
    watcher.mark_processed(sid)
    watcher.poll_once()
    assert replies == []  # 自己的输出不推
    # Web 侧新消息 → 只推增量
    _append_web(store, sid, ["Web 新问题"])
    watcher.poll_once()
    assert len(replies) == 1 and "Web 新问题" in replies[0][1]
    assert "飞书侧回复" not in replies[0][1]


def test_web_created_shared_session_pushed_to_owner(tmp_path):
    """Web 先新建会话（共享当前，无映射键）→ 增量推给 owner 私聊."""
    store, smap, watcher, replies = _make(tmp_path)
    sid = store.create()
    store.set_shared_current(sid)
    watcher.poll_once()  # 建基线
    assert replies == []
    _append_web(store, sid, ["Web 直接发消息"])
    watcher.poll_once()
    assert len(replies) == 1
    assert replies[0][0] == "ou_owner" and "Web 直接发消息" in replies[0][1]


def test_rate_limit_batches(tmp_path, monkeypatch):
    """速率受限：两次增量间隔 < min_interval → 合并为一次推送（基线不丢）."""
    store, smap, watcher, replies = _make(tmp_path)
    sid = smap.get_or_create("p:ou_owner")
    watcher.poll_once()
    _append_web(store, sid, ["第一条"])
    watcher.poll_once()
    assert len(replies) == 1
    _append_web(store, sid, ["第二条"])
    watcher.poll_once()  # 距上次 < 3s → 受限，不推（基线未推进）
    assert len(replies) == 1
    watcher._last_push["ou_owner"] = 0.0  # 模拟时间流逝（放开限速）
    watcher.poll_once()
    assert len(replies) == 2
    assert "第二条" in replies[1][1]


def test_session_cleared_no_push(tmp_path):
    """会话条数变少（清理/瘦身）→ 基线刷新不推送."""
    store, smap, watcher, replies = _make(tmp_path)
    sid = smap.get_or_create("p:ou_owner")
    _append_web(store, sid, ["旧内容"])
    watcher.poll_once()  # 基线=1 条
    assert replies == []
    store.load(sid).messages.clear()
    # 直接重写文件模拟清理（append 只增不减；用 save 覆盖）
    from llm_loop.core.session import Session
    sess = Session(session_id=sid, messages=[])
    store.save(sess)
    watcher.poll_once()
    assert replies == []


def test_corrupt_session_fail_open(tmp_path):
    """会话文件损坏 → 单会话跳过不崩（fail-open）."""
    store, smap, watcher, replies = _make(tmp_path)
    sid = smap.get_or_create("p:ou_owner")
    watcher.poll_once()
    sess_file = tmp_path / "sessions" / f"{sid}.json"
    sess_file.write_text("{broken json", encoding="utf-8")
    watcher.poll_once()  # 不抛异常
    assert replies == []
