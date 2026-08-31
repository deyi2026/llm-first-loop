from __future__ import annotations

from llm_loop.core.injection_labels import InjectionLayer
from llm_loop.core.message import Message, MessageSource
from llm_loop.core.prompt_eligibility import (
    current_turn_program_prompt_eligible,
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

def _current_turn_control(text: str, *, turn_ref: int) -> Message:
    return Message(
        role="system",
        content=text,
        source=MessageSource.SYSTEM,
        metadata={
            "program_origin": True,
            "origin_layer": "status",
            "prompt_lifecycle": "current_turn",
            "turn_ref": turn_ref,
            "injection_kind": "stagnation_reminder",
        },
    )


def test_current_turn_program_control_expires_by_turn_identity():
    current = _current_turn_control("CURRENT-CONTROL", turn_ref=7)
    old = _current_turn_control("OLD-CONTROL", turn_ref=2)
    assert current_turn_program_prompt_eligible(current, current_turn_ref=7) is True
    assert current_turn_program_prompt_eligible(old, current_turn_ref=7) is False
    assert current_turn_program_prompt_eligible(current, current_turn_ref=None) is False


def test_legacy_ephemeral_system_controls_are_not_prompt_eligible():
    for text in (
        "[停滞提醒] old",
        "[搜索空结果提醒] old",
        "[上下文溢出] old",
        "[模型降级: a→b, 原因: x] old",
        "[模型降级] 事实: 全失败",
        "[程序异常] 事实: 程序辅助组件 archive_sink 发生故障。",
    ):
        msg = Message(role="system", content=text, source=MessageSource.SYSTEM)
        assert current_turn_program_prompt_eligible(msg, current_turn_ref=7) is False
    human = Message(role="user", content="[模型降级] 这是用户讨论的文本", source=MessageSource.USER)
    assert current_turn_program_prompt_eligible(human, current_turn_ref=7) is True
    legacy_declaration = Message(
        role="user",
        content=(
            "[声明提醒] 你的最终回答中存在与工具回执不符的完成声明，请知悉"
            "（不影响本次输出，后续请如实声明）。\n旧程序反馈"
        ),
        source=MessageSource.USER,
    )
    assert current_turn_program_prompt_eligible(legacy_declaration, current_turn_ref=7) is False
    quoted = Message(role="user", content="[声明提醒] 请分析这个标签", source=MessageSource.USER)
    assert current_turn_program_prompt_eligible(quoted, current_turn_ref=7) is True


def test_build_keeps_same_turn_control_and_retires_old_or_legacy(build_test_engine):
    engine, _ = build_test_engine([{"content": "unused"}])
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.messages.extend(
        [
            Message(role="user", content="old user", source=MessageSource.USER),
            _current_turn_control("OLD-CONTROL-SHOULD-NOT-PROJECT", turn_ref=0),
            Message(role="system", content="[停滞提醒] LEGACY-SHOULD-NOT-PROJECT", source=MessageSource.SYSTEM),
            Message(role="user", content="current user", source=MessageSource.USER),
            _current_turn_control("CURRENT-CONTROL-SHOULD-PROJECT", turn_ref=3),
        ]
    )
    engine._current_turn_ref = 3
    out = engine._build_llm_messages(
        sess, [], max_chars=200000, planned_label="deepseek/model"
    )
    rendered = str(out)
    assert "OLD-CONTROL-SHOULD-NOT-PROJECT" not in rendered
    assert "LEGACY-SHOULD-NOT-PROJECT" not in rendered
    assert "CURRENT-CONTROL-SHOULD-PROJECT" in rendered
