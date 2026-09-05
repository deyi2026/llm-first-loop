"""Legacy M23 action-chain rules must stay out of the universal model prompt."""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.prompt import build_system_prompt

_LITE = Path(__file__).resolve().parents[2] / "docs" / "ai_rules.lite.md"


def test_action_chain_rule_is_not_global_model_instruction():
    prompt = build_system_prompt()
    lite_text = _LITE.read_text(encoding="utf-8")
    assert "动作链" not in prompt
    assert "动作链" not in lite_text
    assert "ai_rules.lite" not in prompt


def test_prompt_keeps_program_non_arbitration_boundary():
    prompt = build_system_prompt()
    assert "不替你制定任务策略或完成裁决" in prompt
