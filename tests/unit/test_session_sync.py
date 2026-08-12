"""M56 Web/飞书会话同步 单元测试.

覆盖:
- SessionStore pinned 置顶排序 / pin/unpin / channel 序列化兼容（旧 JSON 无字段）
- fork 分支继承 channel、不继承 pinned
- 飞书 SessionMap get_or_create 标记来源 channel
- feishu_push.parse_feishu_channel 通道解析

全部本地 Mock/临时目录，零真实网络。
"""

from __future__ import annotations

import json

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.session import SessionStore
from llm_loop.feishu.session_map import SessionMap


def _store(tmp_path) -> SessionStore:
    return SessionStore(str(tmp_path / "sessions"))


def test_pin_sort_prefers_pinned(tmp_path):
    """置顶会话在列表中优先（同置顶级别内按 updated_at 降序）."""
    store = _store(tmp_path)
    sid_a = store.create()
    sid_b = store.create()
    store.append(sid_a, Message(role="user", content="A", source=MessageSource.USER))
    store.append(sid_b, Message(role="user", content="B", source=MessageSource.USER))
    # 未置顶：b 更新晚，排前
    assert store.list_sessions()[0].session_id == sid_b
    # 置顶 a → a 排前
    assert store.set_pinned(sid_a, True) is True
    assert store.list_sessions()[0].session_id == sid_a
    assert store.list_sessions()[0].pinned is True
    # 取消置顶 → pinned=False（save 会刷新 updated_at，此时 a 仍最新）
    assert store.set_pinned(sid_a, False) is True
    assert store.list_sessions()[0].pinned is False
    # 随后 b 更新 → b 排前（同级别按时间降序）
    store.append(sid_b, Message(role="user", content="B2", source=MessageSource.USER))
    assert store.list_sessions()[0].session_id == sid_b
    assert store.list_sessions()[0].pinned is False


def test_set_pinned_missing_session(tmp_path):
    store = _store(tmp_path)
    assert store.set_pinned("nope", True) is False


def test_channel_serialization_roundtrip(tmp_path):
    """channel 落盘/读取往返一致（version 4）."""
    store = _store(tmp_path)
    sid = store.create()
    assert store.set_channel(sid, "feishu:group:oc_abc") is True
    assert store.load(sid).channel == "feishu:group:oc_abc"
    # 幂等：已标记来源不覆盖
    assert store.set_channel(sid, "web") is True
    assert store.load(sid).channel == "feishu:group:oc_abc"


def test_old_json_missing_fields_backward_compat(tmp_path):
    """旧 JSON（无 pinned/channel）读取缺省向后兼容."""
    store = _store(tmp_path)
    sid = store.create()
    p = store._path(sid)  # noqa: SLF001
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw.pop("pinned")
    raw.pop("channel")
    raw["version"] = 3
    p.write_text(json.dumps(raw), encoding="utf-8")
    sess = store.load(sid)
    assert sess.pinned is False
    assert sess.channel == "web"
    assert store.list_sessions()[0].pinned is False
    assert store.list_sessions()[0].channel == "web"


def test_fork_inherits_channel_not_pinned(tmp_path):
    """fork 分支继承来源 channel；置顶不继承（新分支默认不置顶）."""
    store = _store(tmp_path)
    sid = store.create()
    store.set_channel(sid, "feishu:p2p:ou_x")
    store.set_pinned(sid, True)
    store.append(sid, Message(role="user", content="hello", source=MessageSource.USER))
    new_id = store.fork(sid)
    branch = store.load(new_id)
    assert branch.channel == "feishu:p2p:ou_x"
    assert branch.pinned is False


def test_session_map_marks_feishu_channel(tmp_path):
    """飞书 SessionMap.get_or_create 为新会话标记来源 channel（群聊/私聊）."""
    store = _store(tmp_path)
    smap = SessionMap(store, path=str(tmp_path / "feishu_session_map.json"))
    gid = smap.get_or_create(SessionMap.group_key("oc_group_1"))
    assert store.load(gid).channel == "feishu:group:oc_group_1"
    uid = smap.get_or_create(SessionMap.p2p_key("ou_user_1"))
    assert store.load(uid).channel == "feishu:p2p:ou_user_1"
    # 已有映射复用不重建、channel 保持
    again = smap.get_or_create(SessionMap.group_key("oc_group_1"))
    assert again == gid


def test_parse_feishu_channel():
    from llm_loop.web.feishu_push import parse_feishu_channel

    assert parse_feishu_channel("feishu:group:oc_x") == ("oc_x", "chat_id")
    assert parse_feishu_channel("feishu:p2p:ou_y") == ("ou_y", "open_id")
    assert parse_feishu_channel("web") is None
    assert parse_feishu_channel("feishu:unknown:z") is None
    assert parse_feishu_channel("feishu:group:") is None
    assert parse_feishu_channel("") is None
