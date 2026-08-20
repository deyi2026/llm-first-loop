"""M23: system prompt 结构单测（2026-08-20 P2 适配）.

P2 后 RULE-AI-08（动作链完整）移入 docs/ai_rules.lite.md 约束 8；
L0 prompt 保留哲学根（决策归 AI）与必读指令。动作链语义由 lite↔SoT 校验承担。
"""

from __future__ import annotations

from pathlib import Path

from llm_loop.core.prompt import build_system_prompt

_LITE = Path(__file__).resolve().parents[2] / "docs" / "ai_rules.lite.md"


def test_prompt_has_rule_ai_08():
    """动作链完整规则移入 lite（L0 不再内嵌规则正文，必读指令指向 lite）."""
    prompt = build_system_prompt()
    assert "ai_rules.lite.md" in prompt  # 必读指令（规则承载点）
    lite_text = _LITE.read_text(encoding="utf-8")
    assert "动作链" in lite_text  # 规则语义在 lite


def test_prompt_keeps_decision_principle():
    """哲学根"决策归 AI"保留（RULE-02）."""
    prompt = build_system_prompt()
    assert "程序不替你决策" in prompt
    assert "不约束你" in prompt
