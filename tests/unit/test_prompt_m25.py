"""M25: system prompt 结构单测（FR-ADJ2-WD-02 + spec 20.5-2）.

断言 build_system_prompt() 输出含 RULE-AI-08 三要素①措辞强化（命令句 + 前后值要求），
且 M23 既有语义（三要素②③）与 AI 决定一切保留（不程序强制红线）。
"""

from __future__ import annotations

from llm_loop.core.prompt import build_system_prompt


def test_prompt_has_m25_command_phrase():
    """三要素①命令句强化生效（FR-ADJ2-WD-02 a/b）."""
    prompt = build_system_prompt()
    assert "应调用 adjust_strategy 落地调整" in prompt
    assert "异常指标" in prompt


def test_prompt_has_before_after_values():
    """前后值说明要求 + 正例具体化（FR-ADJ2-WD-02 + WD-03）."""
    prompt = build_system_prompt()
    assert "说明前后值" in prompt
    assert "从 5 调整为 15" in prompt


def test_prompt_keeps_ai_decision_m25():
    """AI 决定一切保留（强化不弱化自主决策，FR-ADJ2-WD-02 c）."""
    prompt = build_system_prompt()
    assert "是否调整由你决定" in prompt
    assert "不强制自查后必须调整" in prompt


def test_prompt_keeps_m23_elements_2_3():
    """M23 三要素②③保留（spec 20.5-2 红线，M23 语义零回归）."""
    prompt = build_system_prompt()
    assert "明确结论" in prompt
    assert "提及本轮所用工具名" in prompt
