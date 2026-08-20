"""M25: system prompt 结构单测（2026-08-20 P2 适配）.

P2 后 RULE-AI-08 三要素（命令句/前后值/决定权）移入 docs/ai_rules.lite.md 约束 8；
L0 保留哲学根（决策归 AI）。M25 语义由 lite↔SoT 校验承担。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.prompt import build_system_prompt

_LITE = Path(__file__).resolve().parents[2] / "docs" / "ai_rules.lite.md"


def test_prompt_has_m25_command_phrase():
    """M25 命令句语义在 lite 约束 8（"落地调整"）."""
    lite_text = _LITE.read_text(encoding="utf-8")
    assert "调整" in lite_text


def test_prompt_has_before_after_values():
    """前后值要求语义在 lite（约束 8 "说明前后值"）. 注: lite 精简为"说明前后值"."""
    lite_text = _LITE.read_text(encoding="utf-8")
    assert "前后值" in lite_text


def test_prompt_keeps_ai_decision_m25():
    """决策归 AI（L0 哲学根）."""
    prompt = build_system_prompt()
    assert "程序不替你决策" in prompt
