"""飞书文本指令审批测试（EVO-20260817 飞书审批 UX 方案 A）.

覆盖:
- parse_approval: 列表/批准/拒绝指令解析（大小写/理由提取/非指令不触发）
- is_approval_allowed: 私聊白名单通过 / 群聊拒绝 / 陌生人拒绝
- approve/reject: 状态机流转 + 幂等（executed 不重复 / accepted 不重审）
- handle_approval: 完整入口（list/accept/reject 回执 + 自动执行触发）
"""

from __future__ import annotations

import json

import pytest

from llm_loop.feishu.approval import (
    approve,
    handle_approval,
    is_approval_allowed,
    list_pending,
    parse_approval,
    reject,
)


# ── parse_approval ──
def test_parse_list_cmd():
    assert parse_approval("审批列表") == ("list", "", "")
    assert parse_approval("  审批  ") == ("list", "", "")
    assert parse_approval("列表") == ("list", "", "")


def test_parse_accept_cmd():
    assert parse_approval("批准 EVO-20260817-abc12345") == ("accept", "EVO-20260817-abc12345", "")
    assert parse_approval("同意 EVO-x123") == ("accept", "EVO-x123", "")
    assert parse_approval("批准 evo-123") == ("accept", "", "")  # 非 EVO- 大写前缀


def test_parse_reject_with_reason():
    r = parse_approval("拒绝 EVO-20260817-abc12345 理由：方案不成熟")
    assert r == ("reject", "EVO-20260817-abc12345", "方案不成熟")
    r2 = parse_approval("拒绝 EVO-123 原因: 成本高")
    assert r2[1] == "EVO-123" and r2[2] == "成本高"


def test_parse_non_approval_returns_none():
    assert parse_approval("今天天气不错") is None
    assert parse_approval("审批流程是怎样的？") is None  # 非精确指令词
    assert parse_approval("") is None


# ── is_approval_allowed ──
class _Msg:
    def __init__(self, sender_id="", is_group=False):
        self.sender_id = sender_id
        self.is_group = is_group


def test_allowed_private_whitelist(tmp_path, monkeypatch):
    smap = tmp_path / "feishu_session_map.json"
    smap.write_text(json.dumps({"p:ou_owner123": "sid1"}), encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert is_approval_allowed(_Msg(sender_id="ou_owner123", is_group=False)) is True


def test_denied_group_or_unknown(tmp_path, monkeypatch):
    smap = tmp_path / "feishu_session_map.json"
    smap.write_text(json.dumps({"p:ou_owner123": "sid1"}), encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert is_approval_allowed(_Msg(sender_id="ou_owner123", is_group=True)) is False  # 群聊拒
    assert is_approval_allowed(_Msg(sender_id="ou_other999", is_group=False)) is False  # 陌生人拒
    assert is_approval_allowed(_Msg(sender_id="", is_group=False)) is False  # 空


# ── approve / reject（状态机）──
def _store(tmp_path):
    from llm_loop.introspection.evolution import EvolutionStore

    st = EvolutionStore(tmp_path / "audit")
    st.submit(
        content="测试建议内容",
        evidence="ev",
        impact_scope="core/loop/engine.py",
        priority="low",
        session_id="s1",
    )
    return st


def test_approve_transitions(tmp_path):
    st = _store(tmp_path)
    sid = st.list()[0]["id"]
    ok, resp, reviewed = approve(st, sid)
    assert ok and reviewed
    assert "已批准" in resp
    assert st.list()[0]["status"] == "accepted"


def test_approve_idempotent(tmp_path):
    st = _store(tmp_path)
    sid = st.list()[0]["id"]
    approve(st, sid)
    ok, resp, reviewed = approve(st, sid)  # 已是 accepted
    assert ok and not reviewed  # 不重复触发执行
    assert "已是 accepted" in resp


def test_approve_unknown(tmp_path):
    st = _store(tmp_path)
    ok, resp, reviewed = approve(st, "EVO-20260817-nope")
    assert not ok and not reviewed and "未找到" in resp


def test_reject_with_reason(tmp_path):
    st = _store(tmp_path)
    sid = st.list()[0]["id"]
    ok, resp = reject(st, sid, "方案不成熟")
    assert ok and "已拒绝" in resp and "方案不成熟" in resp
    assert st.list()[0]["status"] == "rejected"


def test_reject_executed_idempotent(tmp_path):
    st = _store(tmp_path)
    sid = st.list()[0]["id"]
    approve(st, sid)
    # 模拟执行完成
    st._transition(sid, status="executed")
    ok, resp = reject(st, sid)
    assert not ok and "无需拒绝" in resp


# ── handle_approval 完整入口 ──
class _Engine:
    def __init__(self, store):
        self.evolution_store = store
        self.correction_ctx = type("C", (), {"evolve_local_exec": 0, "evolve_exec_whitelist": ""})()
        self.settings = type("S", (), {"audit_dir": ""})()


class _FeishuMsg:
    def __init__(self, sender_id, is_group=False, chat_id=""):
        self.sender_id = sender_id
        self.is_group = is_group
        self.chat_id = chat_id
        self.reply_receive_id = chat_id or sender_id
        self.reply_receive_id_type = "chat_id" if chat_id else "open_id"


def _handler_env(tmp_path, monkeypatch):
    smap = tmp_path / "feishu_session_map.json"
    smap.write_text(json.dumps({"p:ou_owner123": "sid1"}), encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    st = _store(tmp_path)
    replies = []

    def reply_fn(rid, text, rtype):
        replies.append((rid, text, rtype))

    return _Engine(st), replies, reply_fn


def test_handle_list(tmp_path, monkeypatch):
    eng, replies, reply_fn = _handler_env(tmp_path, monkeypatch)
    msg = _FeishuMsg("ou_owner123")
    assert handle_approval(eng, msg, "审批列表", reply_fn) is True
    assert len(replies) == 1 and "待审批" in replies[0][1]


def test_handle_accept_approves_and_replies(tmp_path, monkeypatch):
    eng, replies, reply_fn = _handler_env(tmp_path, monkeypatch)
    sid = eng.evolution_store.list()[0]["id"]
    msg = _FeishuMsg("ou_owner123")
    assert handle_approval(eng, msg, f"批准 {sid}", reply_fn) is True
    assert len(replies) == 1 and "已批准" in replies[0][1]
    assert eng.evolution_store.list()[0]["status"] == "accepted"


def test_handle_reject_denied_unauthorized(tmp_path, monkeypatch):
    eng, replies, reply_fn = _handler_env(tmp_path, monkeypatch)
    msg = _FeishuMsg("ou_stranger")  # 非白名单
    assert handle_approval(eng, msg, "审批列表", reply_fn) is True
    assert len(replies) == 1 and "无权" in replies[0][1]


def test_handle_non_approval_falls_through(tmp_path, monkeypatch):
    eng, replies, reply_fn = _handler_env(tmp_path, monkeypatch)
    msg = _FeishuMsg("ou_owner123")
    assert handle_approval(eng, msg, "帮我查个文件", reply_fn) is False
    assert replies == []


def test_list_pending_empty(tmp_path):
    from llm_loop.introspection.evolution import EvolutionStore

    st = EvolutionStore(tmp_path / "audit")
    assert "无待审批" in list_pending(st)
