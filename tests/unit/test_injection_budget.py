"""INJECTION-GOVERNANCE R2: unified hard budget for program-origin prompt blocks."""

from __future__ import annotations

from llm_loop.core.injection_labels import (
    InjectionLayer,
    PROGRAM_APPENDIX_NOTICE,
    detect_program_layer,
    reference_has_imperative,
)


def test_budget_keeps_whole_blocks_by_priority_and_never_exceeds_limit():
    from llm_loop.core.injection_budget import BudgetBlock, enforce_injection_budget

    blocks = [
        BudgetBlock("ref-big", "R" * 700, InjectionLayer.REFERENCE, slot_kind="memory"),
        BudgetBlock("status", "S" * 220, InjectionLayer.STATUS, slot_kind="gate_note"),
        BudgetBlock("recovery", "P" * 180, InjectionLayer.PROGRAM_RECOVERY, slot_kind="recovery"),
        BudgetBlock("ref-small", "r" * 180, InjectionLayer.REFERENCE, slot_kind="tip"),
    ]
    result = enforce_injection_budget(blocks, budget_chars=640)

    assert result.used_chars <= 640
    assert result.over_budget is True
    assert "recovery" in result.kept_keys
    assert "status" in result.kept_keys
    assert "ref-big" in result.dropped_keys
    # Whole-block invariant: the assembler returns complete source contents only.
    kept = {b.key: b.content for b in result.kept_blocks}
    assert kept["recovery"] == "P" * 180
    assert kept["status"] == "S" * 220
    assert all(content not in {"R" * n for n in range(1, 700)} for content in kept.values())


def test_budget_receipt_is_observability_only_and_not_charged_to_prompt():
    from llm_loop.core.injection_budget import BudgetBlock, enforce_injection_budget

    blocks = [
        BudgetBlock(f"r{i}", "x" * 300, InjectionLayer.REFERENCE, slot_kind="memory")
        for i in range(5)
    ]
    result = enforce_injection_budget(blocks, budget_chars=512)

    assert result.receipt_content
    assert result.used_chars <= 512
    assert result.used_chars == sum(b.cost_chars for b in result.kept_blocks)
    assert not reference_has_imperative(result.receipt_content)
    assert "预算" in result.receipt_content
    assert "部分低优先级块未进入请求" in result.receipt_content


def test_dynamic_group_overhead_is_charged_once_not_per_source():
    from llm_loop.core.injection_budget import BudgetBlock, enforce_injection_budget

    blocks = [
        BudgetBlock("a", "a" * 100, InjectionLayer.STATUS, group="dynamic_appendix"),
        BudgetBlock("b", "b" * 100, InjectionLayer.STATUS, group="dynamic_appendix"),
    ]
    result = enforce_injection_budget(blocks, budget_chars=1000)
    assert result.used_chars == sum(b.cost_chars for b in blocks) + result.group_overhead_chars
    assert result.group_overhead_chars > 0


def test_detect_program_layer_requires_explicit_program_marker():
    assert detect_program_layer("用户原话：继续修复") is None
    assert detect_program_layer(PROGRAM_APPENDIX_NOTICE + "\n[通知·状态]\n状态事实") is InjectionLayer.STATUS
    assert detect_program_layer("[任务·程序恢复]\n恢复事实") is InjectionLayer.PROGRAM_RECOVERY
    assert detect_program_layer("[资料·记忆/经验]\n历史事实") is InjectionLayer.REFERENCE


def test_build_budget_gate_covers_dynamic_appendix_end_to_end(tmp_path):
    # Reuse the production-shape fixture from the R1/1210 golden morphology test.
    from tests.unit.test_injection_fingerprint import _arm_all_slots, _build, _engine

    engine, sess = _engine(tmp_path)
    object.__setattr__(engine.settings, "injection_budget_chars", 900)
    memory_msgs = _arm_all_slots(engine, sess)
    out = _build(engine, sess, memory_msgs)

    program_msgs = [
        m for m in out
        if detect_program_layer(str(m.get("content") or "")) not in (None, InjectionLayer.USER_INSTRUCTION)
    ]
    actual_chars = sum(len(str(m.get("content") or "")) for m in program_msgs)
    assert actual_chars <= 900
    joined = "\n".join(str(m.get("content") or "") for m in program_msgs)
    assert "[注入预算]" not in joined
    assert engine._last_injection_budget.receipt_content.startswith("[注入预算]")
    assert "gate_note" not in joined
    # R2 must prune whole slots; this fixture starts with five program slots.
    assert sum(joined.count(f"[slot:{s}]") for s in ("memory", "interop", "tip", "hotcard", "gate_note")) < 5
    # R1 arbitration remains exactly once on the final dynamic appendix.
    assert joined.count(PROGRAM_APPENDIX_NOTICE) == 1


def test_build_budget_gate_also_covers_persisted_program_blocks_when_cognitive_off(tmp_path):
    from llm_loop.core.injection_labels import render_program_appendix, origin_metadata
    from llm_loop.core.message import Message, MessageSource
    from tests.unit.test_injection_fingerprint import _build, _engine

    engine, sess = _engine(tmp_path)
    object.__setattr__(engine.settings, "cog_runtime_mode", "off")
    object.__setattr__(engine.settings, "injection_budget_chars", 700)
    persisted = render_program_appendix("历史参考事实 " + "Z" * 900, InjectionLayer.REFERENCE)
    engine._current_turn_ref = 0
    sess.messages.append(
        Message(
            role="user",
            content=persisted,
            source=MessageSource.USER,
            metadata=origin_metadata(
                InjectionLayer.REFERENCE, injection_kind="memory_snapshot", turn_ref=0
            ),
        )
    )
    out = _build(engine, sess, [])
    joined = "\n".join(str(m.get("content") or "") for m in out)
    assert "Z" * 100 not in joined
    assert "[注入预算]" not in joined
    assert engine._last_injection_budget.receipt_content.startswith("[注入预算]")
    actual = sum(
        len(str(m.get("content") or ""))
        for m in out
        if detect_program_layer(str(m.get("content") or "")) not in (None, InjectionLayer.USER_INSTRUCTION)
    )
    assert actual <= 700


def test_settings_candidate_default_and_minimum(monkeypatch):
    import llm_loop.config as config_mod
    from llm_loop.core.injection_budget import (
        DEFAULT_INJECTION_BUDGET_CHARS,
        MIN_INJECTION_BUDGET_CHARS,
    )

    # Settings dataclass exposes the R2 candidate explicitly even before env loading.
    assert config_mod.Settings.__dataclass_fields__["injection_budget_chars"].default == DEFAULT_INJECTION_BUDGET_CHARS
    assert MIN_INJECTION_BUDGET_CHARS < DEFAULT_INJECTION_BUDGET_CHARS

    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "http://example.invalid/v1")
    monkeypatch.setenv("INJECTION_BUDGET_CHARS", "1024")
    assert config_mod.load_settings().injection_budget_chars == 1024
    monkeypatch.setenv("INJECTION_BUDGET_CHARS", "1")
    assert config_mod.load_settings().injection_budget_chars == MIN_INJECTION_BUDGET_CHARS
