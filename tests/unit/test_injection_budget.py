"""P1-C: semantic Injection Budget is retired; prompt authority stays deny-by-default."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from llm_loop.core.injection_labels import (
    PROGRAM_APPENDIX_NOTICE,
    InjectionLayer,
    detect_program_layer,
)


def test_semantic_injection_budget_runtime_is_retired() -> None:
    root = Path(__file__).resolve().parents[2]
    assert not (root / "src/llm_loop/core/injection_budget.py").exists()
    assert not (root / "src/llm_loop/core/prompt_build/stages/budget_application.py").exists()
    assert importlib.util.find_spec("llm_loop.core.injection_budget") is None
    assert importlib.util.find_spec(
        "llm_loop.core.prompt_build.stages.budget_application"
    ) is None


def test_settings_has_no_semantic_injection_budget_knob(monkeypatch) -> None:
    import llm_loop.config as config_mod

    assert "injection_budget_chars" not in config_mod.Settings.__dataclass_fields__
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "http://example.invalid/v1")
    # Stale operator env is ignored because no runtime selector consumes it.
    monkeypatch.setenv("INJECTION_BUDGET_CHARS", "1")
    settings = config_mod.load_settings()
    assert not hasattr(settings, "injection_budget_chars")
    assert "injection_budget_chars" not in settings.to_status_dict()


def test_detect_program_layer_requires_explicit_program_marker() -> None:
    assert detect_program_layer("用户原话：继续修复") is None
    assert (
        detect_program_layer(PROGRAM_APPENDIX_NOTICE + "\n[通知·状态]\n状态事实")
        is InjectionLayer.STATUS
    )
    assert (
        detect_program_layer("[任务·程序恢复]\n恢复事实")
        is InjectionLayer.PROGRAM_RECOVERY
    )
    assert (
        detect_program_layer("[资料·记忆/经验]\n历史事实")
        is InjectionLayer.REFERENCE
    )


def test_zero_dynamic_producer_fixed_point_end_to_end(tmp_path) -> None:
    """Armed legacy slots still produce zero program prompt with no budget arbiter."""
    from llm_loop.core.prompt_eligibility import PROMPT_DYNAMIC_PRODUCER_SLOTS
    from tests.unit.test_injection_fingerprint import _arm_all_slots, _build, _engine

    assert frozenset() == PROMPT_DYNAMIC_PRODUCER_SLOTS
    engine, sess = _engine(tmp_path)
    memory_msgs = _arm_all_slots(engine, sess)
    out = _build(engine, sess, memory_msgs)

    program_msgs = [
        m
        for m in out
        if detect_program_layer(str(m.get("content") or ""))
        not in (None, InjectionLayer.USER_INSTRUCTION)
    ]
    assert program_msgs == []
    assert not hasattr(engine._run_state(), "last_build_injections")
    assert not hasattr(engine, "_last_injection_budget")


def test_persisted_program_blocks_are_filtered_before_cognitive_observability(tmp_path) -> None:
    """Historical program-origin content is retrieval-only, not budget-selected context."""
    from llm_loop.core.injection_labels import origin_metadata, render_program_appendix
    from llm_loop.core.message import Message, MessageSource
    from tests.unit.test_injection_fingerprint import _build, _engine

    engine, sess = _engine(tmp_path)
    persisted = render_program_appendix(
        "历史参考事实 " + "Z" * 900, InjectionLayer.REFERENCE
    )
    engine._run_state().current_turn_ref = 0
    sess.messages.append(
        Message(
            role="user",
            content=persisted,
            source=MessageSource.USER,
            metadata=origin_metadata(
                InjectionLayer.REFERENCE,
                injection_kind="memory_snapshot",
                turn_ref=0,
            ),
        )
    )
    out = _build(engine, sess, [])
    joined = "\n".join(str(m.get("content") or "") for m in out)
    assert "Z" * 100 not in joined
    assert "[注入预算]" not in joined
    assert not any(
        detect_program_layer(str(m.get("content") or ""))
        not in (None, InjectionLayer.USER_INSTRUCTION)
        for m in out
    )
