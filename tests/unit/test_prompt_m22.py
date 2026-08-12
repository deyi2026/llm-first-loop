"""M22: system prompt 结构单测（FR-PROMPT-EXEC-PRMP-01/02 + RULE-02）.

断言 build_system_prompt() 输出含 M22 三处 prompt 文本改动：
① 核心原则第 4 条"信息获取优先"；② "可用工具"概述段；③ RULE-AI-07 注入段；
且第 1 条"你决定一切"完整保留（不程序强制红线在 prompt 文本层的体现）。
"""

from __future__ import annotations

from llm_loop.core.prompt import build_system_prompt


def test_prompt_has_information_first():
    """核心原则段含第 4 条"信息获取优先"（FR-PROMPT-EXEC-PRMP-01）."""
    prompt = build_system_prompt()
    assert "信息获取优先" in prompt
    # 精简后"不编造"措辞归 RULE-AI-07 承载（语义等价：不凭推测编造）
    assert "不得凭训练数据推测或编造" in prompt
    # 先取后答 + 是否调用仍由你决定（与 RULE-AI-07 语义一致）
    assert "先调用相应工具获取真实信息" in prompt
    assert "是否调用仍由你决定" in prompt


def test_prompt_keeps_decision_principle():
    """第 1 条"你决定一切"完整保留（RULE-02，不程序强制红线）."""
    prompt = build_system_prompt()
    assert "你决定一切" in prompt
    assert "完全由你决定" in prompt
    # 核心原则段 4 条并列，第 1 条在最前（未被替换/删除）
    core_start = prompt.find("你的核心原则")
    principle1 = prompt.find("1. **你决定一切**", core_start)
    principle4 = prompt.find("4. **信息获取优先**", core_start)
    assert principle1 != -1
    assert principle4 != -1
    assert principle1 < principle4


def test_prompt_has_tool_overview():
    """"工具发现"段含三核心工具（FR-PROMPT-EXEC-PRMP-02）."""
    prompt = build_system_prompt()
    assert "工具发现" in prompt
    for tool in ("read_file", "execute_command", "web_fetch"):
        assert tool in prompt
    # 末尾引导句：完整工具列表见 tools 定义（避免误以为只有三工具）
    assert "完整工具与约束见 tools 定义" in prompt


def test_prompt_has_rule_ai_07():
    """RULE-AI-07 注入段存在且含"工具优先执行"（FR-PROMPT-EXEC-RULE-02）."""
    prompt = build_system_prompt()
    assert "# RULE-AI-07" in prompt
    assert "工具优先执行" in prompt
    # 六关键词（与 test_ai_rules_sync 双向断言同表）
    for kw in (
        "先调用相应工具",
        "不得凭训练数据推测或编造",
        "调整参数或换路径",
        "仍失败再如实说明",
        "不强制调用工具",
    ):
        assert kw in prompt, f"prompt 缺 RULE-AI-07 关键词: {kw}"
    # 灾难性安全段仍在 RULE-AI-07 之后（注入位置正确）
    assert prompt.find("工具优先执行") < prompt.find("灾难性安全")
