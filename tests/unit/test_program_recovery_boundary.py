"""Agency-first recovery contract: runtime retry may never become model-visible text."""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.injection_labels import InjectionLayer, origin_metadata, render_program_appendix
from llm_loop.core.message import Message, MessageSource


def test_program_recovery_module_is_legacy_detector_only() -> None:
    import llm_loop.core.program_recovery as recovery

    assert hasattr(recovery, "is_program_recovery_message")
    for retired in (
        "ProgramRecoveryAction",
        "render_program_recovery",
        "make_program_recovery_message",
        "PROGRAM_RECOVERY_SLOT",
    ):
        assert not hasattr(recovery, retired), retired


def test_program_recovery_is_not_a_prompt_producer_or_runtime_slot() -> None:
    from llm_loop.core.loop.runstate import RunState
    from llm_loop.core.prompt_eligibility import PROMPT_DYNAMIC_PRODUCER_SLOTS

    assert "program_recovery" not in PROMPT_DYNAMIC_PRODUCER_SLOTS
    assert "program_recovery_tail_message" not in RunState.__dataclass_fields__


def test_legacy_persisted_recovery_is_audit_history_not_provider_context(tmp_path: Path) -> None:
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
    engine._run_state().current_turn_ref = 0

    out = _build(engine, sess, [])
    joined = "\n".join(str(m.get("content") or "") for m in out)

    assert stale in sess.messages  # durable audit truth remains
    assert "[任务·程序恢复]" not in joined
    assert "旧恢复动作" not in joined
    assert joined.endswith(truth)


def test_human_text_that_mentions_legacy_marker_is_never_filtered(tmp_path: Path) -> None:
    from tests.unit.test_injection_fingerprint import _build, _engine

    engine, sess = _engine(tmp_path)
    truth = "[程序续跑] 这是我本人输入的测试文本，请原样分析。"
    sess.messages[0].content = truth
    engine._run_state().current_turn_ref = 0

    out = _build(engine, sess, [])

    assert sess.messages[0].source is MessageSource.USER
    assert out[-1]["role"] == "user"
    assert out[-1]["content"] == truth
    assert float(out[-1].get("_message_time_ts") or 0.0) > 0



def test_runtime_retry_api_is_retired_but_historical_event_schema_remains_readable() -> None:
    from llm_loop.core.loop.engine_services.recovery_controller import RecoveryController
    from llm_loop.event_log.model import EVENT_PROGRAM_RECOVERY, REGISTRY

    assert not hasattr(RecoveryController, "_err1210_try_auto_continue")
    assert not hasattr(RecoveryController, "_err1210_try_runtime_retry")
    spec = REGISTRY.spec(EVENT_PROGRAM_RECOVERY)
    assert spec is not None  # append-only historical rows remain readable


def test_real_single_user_1210_has_zero_program_prompt_and_zero_retry(tmp_path: Path, monkeypatch) -> None:
    from tests.unit.test_err1210_recovery import _e1210, _mk

    engine, fake = _mk(tmp_path, monkeypatch, responses=[_e1210()])
    sid = engine.session.create()
    result = engine.run(sid, "真实用户任务")
    assert "LLM 调用异常" in result.final_answer
    assert len(fake.calls) == 1
    joined = "\n".join(str(m.get("content") or "") for m in fake.calls[0]["messages"])
    assert "[任务·程序恢复]" not in joined
    assert "runtime_rebuild_retry_once" not in joined
