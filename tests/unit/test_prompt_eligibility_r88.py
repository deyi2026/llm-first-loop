from __future__ import annotations

from llm_loop.core.injection_labels import InjectionLayer
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt_eligibility import (
    dynamic_prompt_layer,
    memory_snapshot_prompt_eligible,
)


def _memory(text: str, turn_ref=None) -> Message:
    md = {"injection_kind": "memory_snapshot", "program_origin": True, "origin_layer": "reference"}
    if turn_ref is not None:
        md["turn_ref"] = turn_ref
    return Message(role="user", content=text, source=MessageSource.USER, metadata=md)


def test_unknown_dynamic_producer_is_not_prompt_eligible():
    assert dynamic_prompt_layer("future plugin text", slot_kind="future_plugin") is None
    assert dynamic_prompt_layer("unattributed text", slot_kind=None) is None
    assert dynamic_prompt_layer("known status", slot_kind="gate_note") is InjectionLayer.STATUS
    assert dynamic_prompt_layer("[相关记忆] fact", slot_kind="memory") is InjectionLayer.REFERENCE


def test_memory_snapshot_requires_exact_current_turn_identity():
    current = _memory("CURRENT-MEMORY", turn_ref=7)
    old = _memory("OLD-MEMORY", turn_ref=2)
    legacy = _memory("LEGACY-MEMORY")
    assert memory_snapshot_prompt_eligible(current, current_turn_ref=7) is True
    assert memory_snapshot_prompt_eligible(old, current_turn_ref=7) is False
    assert memory_snapshot_prompt_eligible(legacy, current_turn_ref=7) is False
    assert memory_snapshot_prompt_eligible(current, current_turn_ref=None) is False


def test_build_hides_old_memory_snapshot_but_keeps_current_turn(build_test_engine):
    engine, _ = build_test_engine([{"content": "unused"}])
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.messages.extend(
        [
            Message(role="user", content="old user", source=MessageSource.USER),
            _memory("OLD-MEMORY-SHOULD-NOT-PROJECT", turn_ref=0),
            Message(role="assistant", content="old answer", source=MessageSource.USER),
            Message(role="user", content="current user", source=MessageSource.USER),
            _memory("CURRENT-MEMORY-SHOULD-PROJECT", turn_ref=3),
        ]
    )
    engine._current_turn_ref = 3
    out = engine._build_llm_messages(
        sess, [], max_chars=200000, planned_label="deepseek/model"
    )
    rendered = str(out)
    assert "OLD-MEMORY-SHOULD-NOT-PROJECT" not in rendered
    assert "CURRENT-MEMORY-SHOULD-PROJECT" in rendered


def test_local_provider_no_longer_gets_behavior_patch(build_test_engine):
    engine, _ = build_test_engine([{"content": "unused"}])
    sid = engine.session.create()
    sess = engine.session.load(sid)
    out = engine._build_llm_messages(
        sess, [], max_chars=200000, planned_label="local/model"
    )
    assert "本地模型行为提示" not in str(out)
    assert "改≤3文件自主执行" not in str(out)
