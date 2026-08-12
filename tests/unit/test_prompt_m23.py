"""M23: system prompt 结构单测（FR-CHAIN-RULE-02 + PRMP-01/02/03 + RULE-02）.

断言 build_system_prompt() 输出含 M23 动作链完整性引导三处文本：
① RULE-AI-08 注入段；② RULE-AI-02 段"自查→明确结论"引导句；③ 回答提及工具名引导句；
且第 1 条"你决定一切"完整保留（不程序强制红线在 prompt 文本层的体现）。
"""

from __future__ import annotations

from llm_loop.core.prompt import build_system_prompt


def test_prompt_has_rule_ai_08():
    """RULE-AI-08 注入段存在且含"动作链完整"（FR-CHAIN-RULE-02）."""
    prompt = build_system_prompt()
    assert "# RULE-AI-08" in prompt
    assert "动作链完整" in prompt


def test_prompt_has_self_check_conclusion():
    """自查→明确结论/调整闭环引导句存在（FR-CHAIN-PRMP-01，场景 a 型）."""
    prompt = build_system_prompt()
    assert "走完动作链" in prompt
    # M25: 三要素①措辞强化（许可型"继续调用"→命令句"应调用"，见 FR-ADJ2-WD-02）
    assert "应调用 adjust_strategy 落地调整" in prompt
    assert "明确结论" in prompt


def test_prompt_mentions_tool_names():
    """回答提及工具名引导句存在（FR-CHAIN-PRMP-02，场景 f 型）."""
    prompt = build_system_prompt()
    assert "提及本轮所用工具名" in prompt
    assert "使动作链可核验可追溯" in prompt


def test_prompt_keeps_decision_principle():
    """第 1 条"你决定一切"完整保留 + "不强制"表述（RULE-02，不程序强制红线）."""
    prompt = build_system_prompt()
    assert "你决定一切" in prompt
    assert "完全由你决定" in prompt
    assert "不强制" in prompt


def test_prompt_rule_ai_08_position():
    """RULE-AI-08 段在 RULE-AI-07 之后、灾难性安全段之前（注入位置正确）."""
    prompt = build_system_prompt()
    assert prompt.find("# RULE-AI-07") < prompt.find("# RULE-AI-08") < prompt.find("灾难性安全")
