"""Legacy M25 execution-format rules are offline/skill concerns, not universal prompt."""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.prompt import build_system_prompt

_LITE = Path(__file__).resolve().parents[2] / "docs" / "ai_rules.lite.md"


def test_before_after_and_action_format_rules_are_not_global():
    prompt = build_system_prompt()
    lite_text = _LITE.read_text(encoding="utf-8")
    for forbidden in ("前后值", "动作链", "回答报工具名"):
        assert forbidden not in prompt
        assert forbidden not in lite_text


def test_prompt_keeps_agency_not_methodology():
    prompt = build_system_prompt()
    assert "不替你制定任务策略或完成裁决" in prompt
