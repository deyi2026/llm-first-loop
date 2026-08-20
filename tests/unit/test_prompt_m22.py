"""M22: system prompt 结构单测（FR-PROMPT-EXEC-PRMP-01/02 + RULE-02，2026-08-20 P2 适配）.

P2 后 prompt.py 为 L0 稳定核心（架构: docs/ARCHITECTURE-cache-stable-rules.md）:
- 行为规则（含 RULE-AI-07 工具优先）移入 docs/ai_rules.lite.md，由模型按需读取；
- L0 保留: 哲学根（决策归 AI）+ 工作方式（信息获取优先语义）+ 必读指令（指向 lite）。
断言适配 L0 文案；规则细节由 test_ai_rules_sync 的 lite↔SoT 校验承担。
"""

from __future__ import annotations

from llm_loop.core.prompt import build_system_prompt


def test_prompt_has_information_first():
    """L0 工作方式含"信息获取优先"语义（FR-PROMPT-EXEC-PRMP-01）."""
    prompt = build_system_prompt()
    assert "先取真实信息再回答" in prompt  # 信息获取优先（L0 措辞）
    assert "不凭训练数据编造" in prompt  # 不编造（原 RULE-AI-07 语义核心）
    assert "最终回答前对照本轮工具回执如实声明完成情况" in prompt  # 诚实


def test_prompt_keeps_decision_principle():
    """哲学根"决策归 AI"保留（RULE-02，不程序强制红线）."""
    prompt = build_system_prompt()
    assert "程序不替你决策" in prompt
    assert "不约束你" in prompt
    # 决策原则位于 prompt 开头（哲学根位置未被替换）
    assert prompt.find("程序不替你决策") < prompt.find("协议硬约束")


def test_prompt_has_must_read_instruction():
    """L0 必读指令存在（P2 核心：规则移出前缀后由模型读取）."""
    prompt = build_system_prompt()
    assert "ai_rules.lite.md" in prompt
    assert "read_file(full=true)" in prompt  # 防截断读取
    assert "rules_version" in prompt  # 版本信号经 architecture_status


def test_prompt_has_protocol_hard_constraints():
    """L0 保留协议硬约束（M20/数据完整性/不静默）."""
    prompt = build_system_prompt()
    for kw in ("reasoning_content", "tool_call_id", "不静默", "数据完整性"):
        assert kw in prompt, f"L0 缺协议硬约束: {kw}"
