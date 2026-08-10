"""T47: AI 规则一致性校验（FR-AUD-DOC-02）.

docs/ai_rules.md 为唯一规则真相源，core/prompt.py 为其派生呈现。
断言七条规则（RULE-AI-01~07）关键动作句双向包含，防漂移。
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

# 七条规则 → 关键动作句（语义关键词，文档与 prompt 都必须包含）
_RULE_KEYWORDS = {
    "RULE-AI-01": ["诚实自查", "对照本轮工具回执", "不得虚构完成"],
    "RULE-AI-02": ["参数自主规范", "核对参数格式", "自行更正后重试", "主动管理自查"],
    "RULE-AI-03": ["停滞自主调整", "重复相同动作", "主动调整策略"],
    "RULE-AI-04": ["程序故障处理", "程序异常", "继续作答"],
    "RULE-AI-05": ["记忆沉淀", "[[memory]]", "长期记住"],
    "RULE-AI-06": [
        "架构演进与自我评估",
        "submit_evolution",
        "self_evaluate",
        # M16 审计四子规则关键动作句（先 SoT 后 prompt 防漂移）
        "对比执行前后架构状态",
        "不得虚构通过",
        "业务数据",
        "仅建议、等待人工执行",
        # M17 FR-REVIEW-AI-01: 完成登记闭环（子规则 4 追加句）
        "evolution_complete",
        # M18 AA9: SoT 收敛（异常触发已移除，正文与程序一致）
        "定期/里程碑触发",
    ],
    # M22: 文档规则层引导（先取后答 + 不得编造，不强制调用工具）
    "RULE-AI-07": [
        "工具优先执行",  # 规则编号名（SoT 标题 + prompt 注入段标题）
        "先调用相应工具",  # 三要素①先取后答
        "不得凭训练数据推测或编造",  # 三要素②禁止编造
        "调整参数或换路径",  # 三要素③失败调整
        "仍失败再如实说明",  # 三要素③失败兑底（与 RULE-AI-03 衔接）
        "不强制调用工具",  # 程序角色（AI 决定一切保留）
    ],
}


def _read(path: str) -> str:
    return (_ROOT / path).read_text(encoding="utf-8")


def test_ai_rules_md_has_all_numbers():
    """ai_rules.md 含全部 RULE-AI 编号."""
    doc = _read("docs/ai_rules.md")
    for rule_id in _RULE_KEYWORDS:
        assert rule_id in doc, f"ai_rules.md 缺 {rule_id}"


def test_prompt_has_rule_numbers():
    """prompt.py 含 RULE-AI 编号注释."""
    prompt = _read("src/llm_loop/core/prompt.py")
    for rule_id in _RULE_KEYWORDS:
        assert f"# {rule_id}" in prompt, f"prompt.py 缺 {rule_id} 注释"


def test_rules_consistent_both_sides():
    """五条规则关键动作句在 ai_rules.md 与 prompt.py 双向包含（防漂移）."""
    doc = _read("docs/ai_rules.md")
    prompt = _read("src/llm_loop/core/prompt.py")
    for rule_id, keywords in _RULE_KEYWORDS.items():
        # RULE-AI-06 含四子规则（M16 审计）/ RULE-AI-07 含程序角色+正反例（M22）→ 更大窗口；其余规则 600 字符
        window = 1600 if rule_id in {"RULE-AI-06", "RULE-AI-07"} else 600
        doc_section = doc[doc.find(rule_id) :][:window]
        prompt_section = prompt[prompt.find(rule_id) :][:window]
        for kw in keywords:
            assert kw in doc_section or kw in doc[: doc.find(rule_id) + 40], (
                f"ai_rules.md {rule_id} 缺关键词: {kw}"
            )
            assert kw in prompt_section or kw in prompt[: prompt.find(rule_id) + 40], (
                f"prompt.py {rule_id} 缺关键词: {kw}"
            )
