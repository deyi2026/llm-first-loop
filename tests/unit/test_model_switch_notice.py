"""R8.8 model switch is observability-only and never prompt/history material."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from llm_loop.core.loop.engine import LoopEngine


def _engine() -> Any:
    eng: Any = object.__new__(LoopEngine)
    eng._tip_tail_messages = None
    eng._actions = []
    eng._record_action = lambda kind, action, detail: eng._actions.append((kind, action, detail))
    return eng


def _sess():
    return SimpleNamespace(
        messages=[
            SimpleNamespace(role="user", content="SECRET-RECENT-USER-TEXT"),
            SimpleNamespace(role="assistant", content="SECRET-RECENT-ASSISTANT-TEXT"),
        ],
        session_id="s1",
    )


def test_switch_records_observability_without_prompt_mutation():
    eng = _engine()
    sess = _sess()
    before = list(sess.messages)
    eng._inject_switch_notice("deepseek/deepseek-v4-flash", "minimax/MiniMax-M3", sess)
    assert sess.messages == before
    assert eng._tip_tail_messages is None
    assert eng._actions == [
        ("model.switch", "observed", "deepseek/deepseek-v4-flash->minimax/MiniMax-M3")
    ]
    assert "SECRET-RECENT" not in str(eng._actions)


def test_switch_noop_same_model():
    eng = _engine()
    sess = _sess()
    eng._inject_switch_notice("deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-flash", sess)
    assert eng._actions == []


def test_switch_records_each_real_transition_without_accumulating_messages():
    eng = _engine()
    sess = _sess()
    before = list(sess.messages)
    eng._inject_switch_notice("deepseek/deepseek-v4-flash", "minimax/MiniMax-M3", sess)
    eng._inject_switch_notice("minimax/MiniMax-M3", "deepseek/deepseek-v4-flash", sess)
    assert sess.messages == before
    assert len(eng._actions) == 2


def test_switch_empty_from_noop():
    eng = _engine()
    sess = _sess()
    eng._inject_switch_notice("", "minimax/MiniMax-M3", sess)
    assert eng._actions == []
