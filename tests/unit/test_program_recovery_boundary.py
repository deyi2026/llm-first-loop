"""INJECTION-GOVERNANCE R4: program recovery is a single-use, single-action boundary."""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata, render_program_appendix
from llm_loop.core.message import Message, MessageSource


def _tail_user_run(messages: list[dict]) -> int:
    n = 0
    for message in reversed(messages):
        if message.get("role") != "user":
            break
        n += 1
    return n


def test_canonical_recovery_template_is_single_action_and_closed_scope() -> None:
    from llm_loop.core.program_recovery import (
        ProgramRecoveryAction,
        render_program_recovery,
    )

    text = render_program_recovery(ProgramRecoveryAction.RETRY_CURRENT_REQUEST_ONCE)

    assert text.startswith("[任务·程序恢复]\n")
    assert text.count("[任务·程序恢复]") == 1
    assert "恢复动作=在已重建上下文中重试本轮请求一次。" in text
    assert "非用户新指令" in text
    assert "当前用户原话" in text
    assert "[程序续跑]" not in text
    assert "请继续" not in text
    assert "勿重复" not in text
    for forbidden in ("顺便", "下一阶段", "扩展任务", "额外任务", "继续后续"):
        assert forbidden not in text


def test_auto_continue_arms_one_ephemeral_recovery_without_persisting_message(
    tmp_path: Path, monkeypatch
) -> None:
    from llm_loop.core.program_recovery import ProgramRecoveryAction
    from tests.unit.test_err1210_recovery import _e1210, _mk

    engine, _fake = _mk(tmp_path, monkeypatch, responses=[])
    sid = engine.session.create()
    sess = engine.session.load(sid)
    sess.messages.append(
        Message(role="user", content="当前真实任务", source=MessageSource.USER)
    )
    engine._current_turn_ref = len(sess.messages) - 1
    engine._err1210_run_begin()
    before = list(sess.messages)

    assert engine._err1210_try_auto_continue(_e1210(), sess) is True
    assert sess.messages == before  # recovery is runtime-only, never long-lived conversation history
    pending = engine._program_recovery_tail_message
    assert pending is not None
    assert pending.metadata.get("injection_kind") == "program_recovery"
    assert pending.metadata.get("recovery_action") == str(
        ProgramRecoveryAction.RETRY_CURRENT_REQUEST_ONCE
    )
    assert pending.metadata.get("recovery_turn_ref") == engine._current_turn_ref
    assert pending.metadata.get("persisted_injection") is not True

    # Per-run guard and single slot make a second recovery block structurally impossible.
    first = pending
    assert engine._err1210_try_auto_continue(_e1210(), sess) is False
    assert engine._program_recovery_tail_message is first


def test_build_consumes_recovery_once_and_r6_keeps_exact_user_tail(tmp_path: Path) -> None:
    from llm_loop.core.program_recovery import make_program_recovery_message
    from llm_loop.core.user_truth_wire import USER_TRUTH_SEPARATOR
    from tests.unit.test_injection_fingerprint import _build, _engine

    engine, sess = _engine(tmp_path)
    engine._current_turn_ref = 0
    truth = sess.messages[0].content
    engine._program_recovery_tail_message = make_program_recovery_message(turn_ref=0)

    out = _build(engine, sess, [])

    assert engine._program_recovery_tail_message is None
    assert _tail_user_run(out) == 1
    envelope = out[-1]
    content = str(envelope.get("content") or "")
    assert content.count("[任务·程序恢复]") == 1
    assert content.count(USER_TRUTH_SEPARATOR) == 1
    assert content.index("[任务·程序恢复]") < content.index(USER_TRUTH_SEPARATOR)
    assert content.endswith(truth)
    # Recovery is the executable exception and must precede any background-only notice.
    recovery_at = content.index("[任务·程序恢复]")
    notice_at = content.find("[程序附录·非用户输入]")
    if notice_at >= 0:
        assert recovery_at < notice_at < content.index(USER_TRUTH_SEPARATOR)

    # Same turn, second build: one-shot slot is gone; it cannot leak into tool follow-up/rebuilds.
    out2 = _build(engine, sess, [])
    assert all("[任务·程序恢复]" not in str(m.get("content") or "") for m in out2)


def test_r2_budget_keeps_recovery_as_high_priority_without_breaking_r6(tmp_path: Path) -> None:
    from llm_loop.core.program_recovery import make_program_recovery_message
    from tests.unit.test_injection_fingerprint import _arm_all_slots, _build, _engine

    engine, sess = _engine(tmp_path)
    object.__setattr__(engine.settings, "cog_runtime_mode", "enforce")
    object.__setattr__(engine.settings, "injection_budget_chars", 512)
    engine._current_turn_ref = 0
    engine._program_recovery_tail_message = make_program_recovery_message(turn_ref=0)
    memory_msgs = _arm_all_slots(engine, sess)

    out = _build(engine, sess, memory_msgs)
    joined = "\n".join(str(m.get("content") or "") for m in out)
    result = engine._last_injection_budget

    assert "[任务·程序恢复]" in joined
    assert result.used_chars <= 512
    assert any(b.layer is InjectionLayer.PROGRAM_RECOVERY for b in result.kept_blocks)
    assert _tail_user_run(out) == 1
    assert joined.endswith(sess.messages[0].content)


def test_legacy_persisted_recovery_is_audit_history_not_future_executable_context(
    tmp_path: Path,
) -> None:
    from tests.unit.test_injection_fingerprint import _build, _engine

    engine, sess = _engine(tmp_path)
    truth = sess.messages[0].content
    stale = Message(
        role="user",
        content=render_program_appendix(
            "[程序续跑] 旧恢复动作：继续某个历史任务。",
            InjectionLayer.PROGRAM_RECOVERY,
        ),
        source=MessageSource.SYSTEM,
        metadata=origin_metadata(
            InjectionLayer.PROGRAM_RECOVERY,
            injection_kind="program_recovery",
            persisted_injection=True,
        ),
    )
    sess.messages.append(stale)
    engine._current_turn_ref = 0

    out = _build(engine, sess, [])
    joined = "\n".join(str(m.get("content") or "") for m in out)

    assert stale in sess.messages  # audit/storage truth is preserved
    assert "[任务·程序恢复]" not in joined
    assert "旧恢复动作" not in joined
    assert joined.endswith(truth)


def test_recovery_slot_is_dropped_when_current_human_boundary_is_unavailable(tmp_path: Path) -> None:
    from llm_loop.core.program_recovery import make_program_recovery_message
    from tests.unit.test_injection_fingerprint import _build, _engine

    engine, sess = _engine(tmp_path)
    engine._current_turn_ref = 0
    sess.messages.append(
        Message(role="assistant", content="already advanced", source=MessageSource.SYSTEM)
    )
    engine._program_recovery_tail_message = make_program_recovery_message(turn_ref=0)

    out = _build(engine, sess, [])

    assert engine._program_recovery_tail_message is None
    assert all("[任务·程序恢复]" not in str(m.get("content") or "") for m in out)


def test_program_recovery_event_type_is_registered() -> None:
    from llm_loop.event_log.model import EVENT_PROGRAM_RECOVERY, REGISTRY

    spec = REGISTRY.spec(EVENT_PROGRAM_RECOVERY)
    assert spec is not None
    assert set(spec.fields) == {"action", "trigger", "turn_ref", "scope"}


def test_real_auto_continue_second_payload_has_one_recovery_and_no_future_leak(
    tmp_path: Path, monkeypatch
) -> None:
    from llm_loop.core.program_recovery import is_program_recovery_message
    from llm_loop.event_log.model import EVENT_PROGRAM_RECOVERY
    from llm_loop.event_log.store import EventStore
    from tests.unit.test_err1210_recovery import _e1210, _mk, _resp

    monkeypatch.setenv("ERR1210_BLIND_RETRY", "0")
    engine, fake = _mk(
        tmp_path,
        monkeypatch,
        responses=[_e1210(), _resp("恢复成功"), _resp("新任务回答")],
    )
    engine._event_store = EventStore(tmp_path / "event_logs", enabled=True)
    sid = engine.session.create()

    first = engine.run(sid, "真实用户任务")
    assert "恢复成功" in first.final_answer
    assert len(fake.calls) == 2
    first_wire = fake.calls[0]["messages"]
    recovery_wire = fake.calls[1]["messages"]
    assert all("[任务·程序恢复]" not in str(m.get("content") or "") for m in first_wire)
    joined = "\n".join(str(m.get("content") or "") for m in recovery_wire)
    assert joined.count("[任务·程序恢复]") == 1
    assert joined.endswith("真实用户任务")
    assert _tail_user_run(recovery_wire) == 1

    persisted = engine.session.load(sid)
    assert not any(is_program_recovery_message(m) for m in persisted.messages)
    events = list(engine._event_store.read(sid))
    recovery_events = [e for e in events if e.type == EVENT_PROGRAM_RECOVERY]
    assert len(recovery_events) == 1
    assert recovery_events[0].payload["action"] == "retry_current_request_once"
    assert recovery_events[0].payload["scope"] == "next_build_only"

    second = engine.run(sid, "新的用户任务")
    assert "新任务回答" in second.final_answer
    assert len(fake.calls) == 3
    future_wire = fake.calls[2]["messages"]
    assert all("[任务·程序恢复]" not in str(m.get("content") or "") for m in future_wire)


def test_human_text_that_mentions_legacy_recovery_marker_is_never_filtered(tmp_path: Path) -> None:
    """Adversarial guard: labels in real human text never grant program-origin semantics."""
    from tests.unit.test_injection_fingerprint import _build, _engine

    engine, sess = _engine(tmp_path)
    truth = "[程序续跑] 这是我本人输入的测试文本，请原样分析。"
    sess.messages[0].content = truth
    engine._current_turn_ref = 0

    out = _build(engine, sess, [])

    assert sess.messages[0].source is MessageSource.USER
    assert out[-1] == {"role": "user", "content": truth}


def test_recovery_runtime_state_is_session_scoped(tmp_path: Path) -> None:
    """R4 concurrency invariant: one session's pending recovery cannot leak into another."""
    from llm_loop.core.program_recovery import make_program_recovery_message
    from llm_loop.core.run_context import current_session_id
    from tests.unit.test_injection_fingerprint import _engine

    engine, _sess = _engine(tmp_path)

    tok_a = current_session_id.set("r4-session-A")
    try:
        engine._program_recovery_tail_message = make_program_recovery_message(turn_ref=3)
        engine._auto_continue_1210 = 1
        engine._err1210_run_seq = 7
    finally:
        current_session_id.reset(tok_a)

    tok_b = current_session_id.set("r4-session-B")
    try:
        assert engine._program_recovery_tail_message is None
        assert engine._auto_continue_1210 == 0
        assert engine._err1210_run_seq == 0
    finally:
        current_session_id.reset(tok_b)

    tok_a = current_session_id.set("r4-session-A")
    try:
        assert engine._program_recovery_tail_message is not None
        assert engine._program_recovery_tail_message.metadata["recovery_turn_ref"] == 3
        assert engine._auto_continue_1210 == 1
        assert engine._err1210_run_seq == 7
    finally:
        current_session_id.reset(tok_a)
