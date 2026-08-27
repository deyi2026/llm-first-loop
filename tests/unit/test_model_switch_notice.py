"""模型切换通知：按会话持久化，避免瞬时 tail 破坏下一请求前缀。"""
from __future__ import annotations

from types import SimpleNamespace

from llm_loop.core.loop.engine import LoopEngine


def _engine():
    eng = object.__new__(LoopEngine)
    eng._tip_tail_messages = None
    eng._events = []
    eng._append_message_event = lambda sess, msg: eng._events.append(msg)
    return eng


def _sess():
    return SimpleNamespace(messages=[], session_id="s1")


def test_switch_notice_persisted_on_model_change():
    eng = _engine()
    sess = _sess()
    eng._inject_switch_notice("deepseek/deepseek-v4-flash", "minimax/MiniMax-M3", sess)
    assert eng._tip_tail_messages is None
    assert len(sess.messages) == 1
    msg = sess.messages[0]
    assert msg.role == "user"
    assert "模型切换感知" in msg.content
    assert "deepseek/deepseek-v4-flash" in msg.content
    assert "minimax/MiniMax-M3" in msg.content
    assert "search_archive" in msg.content
    assert msg.metadata.get("persisted_injection") is True
    assert msg.metadata.get("injection_kind") == "model_switch_notice"
    assert eng._events == [msg]


def test_switch_notice_noop_same_model():
    eng = _engine()
    sess = _sess()
    eng._inject_switch_notice("deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-flash", sess)
    assert sess.messages == []


def test_switch_notice_accumulates_persistently():
    eng = _engine()
    sess = _sess()
    eng._inject_switch_notice("deepseek/deepseek-v4-flash", "minimax/MiniMax-M3", sess)
    eng._inject_switch_notice("minimax/MiniMax-M3", "deepseek/deepseek-v4-flash", sess)
    assert len(sess.messages) == 2
    assert "minimax/MiniMax-M3" in sess.messages[0].content
    assert "deepseek/deepseek-v4-flash" in sess.messages[1].content


def test_switch_notice_empty_from_noop():
    eng = _engine()
    sess = _sess()
    eng._inject_switch_notice("", "minimax/MiniMax-M3", sess)
    assert sess.messages == []
