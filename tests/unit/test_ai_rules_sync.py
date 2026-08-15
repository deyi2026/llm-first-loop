"""T47: AI 规则一致性校验（FR-AUD-DOC-02）.

docs/ai_rules.md 为唯一规则真相源，core/prompt.py 为其派生呈现。
断言十二条规则（RULE-AI-00~11）关键动作句双向包含，防漂移。
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

# 七条规则 → 关键动作句（语义关键词，文档与 prompt 都必须包含）
_RULE_KEYWORDS = {
    "RULE-AI-00": [
        "AI 优先总纲",
        "感官和手脚",

        "不自动压缩/重试/摘要",
        "如实反馈",
        "避免程序错误影响",
        # round4 E1: 自动摘要边界（P2 补充，双向包含防漂移）
        "自动摘要边界",
        "只作用于",
        "不注入",
    ],
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
    # M23: 动作链完整性引导（自查→调整/明确结论 + 回答可追溯，不强制调整）
    "RULE-AI-08": [
        "动作链完整",  # 规则编号名（SoT 标题 + prompt 注入段标题）
        "明确结论",  # 三要素②自查→明确结论闭环
        "adjust_strategy",  # 三要素①自查→调整闭环（修正工具名）
        "提及本轮所用工具名",  # 三要素③回答可追溯
        "不强制调用工具",  # 程序角色（AI 决定一切保留）
        # M25（FR-ADJ2-SYNC-01）: 三要素①措辞强化——命令句 + 前后值要求
        # 注意: 命令句关键词用"应调用"而非"应调用 adjust_strategy"——SoT 工具名带反引号致子串不匹配
        "应调用",  # 三要素①命令句（M25 强化）
        "前后值",  # 三要素①前后值说明要求（M25 强化）
        "从 5 调整为 15",  # 三要素①正例前后值具体化（M25 强化）
    ],
    # RULE-AI-09: 模型切换自主（切前自查/带 reason/切后必验/诚实边界）
    "RULE-AI-09": [
        "模型切换自主",  # 规则编号名（SoT 标题 + prompt 注入段标题）
        "model_catalog",  # 切前查目录
        "切后必验",  # 切换后复查确认生效
        "用户显式选择",  # 诚实边界（显式选择不自动降级）
        "默认装配",  # 仅默认装配走 MODEL_FALLBACKS 链
        "密钥不出域",  # 注册表只存 env 名，不回显 key
    ],
    # RULE-AI-10: 每轮自主检查清单（自我评估/演进待办/待审/窗口/思考链自知）
    "RULE-AI-10": [
        "每轮自主检查清单",  # 规则编号名（SoT 标题 + prompt 注入段标题）
        "self_evaluate",  # 自我评估触发
        "evolution_complete",  # 演进待办登记闭环
        "model_window",  # 上下文窗口自查
        "思考链自知",  # M66 思考链省略自知
    ],
    # RULE-AI-11: 截断提炼 + 轮次耗尽自主归因（2026-08-15 截断信号强化）
    "RULE-AI-11": [
        "截断提炼与轮次耗尽自主归因",  # 规则编号名
        "提炼记录",  # 截断信号 → 先提炼要点再推理
        "最终总结",  # 要点纳入最终总结
        "轮次决策请求",  # 耗尽信号
        "工具使用错误",  # 归因情形①
        "adjust_strategy",  # 正常推进 → 调大续跑
        "硬上限 500",  # 程序兜底边界
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
    """十二条规则关键动作句在 ai_rules.md 与 prompt.py 双向包含（防漂移）."""
    doc = _read("docs/ai_rules.md")
    prompt = _read("src/llm_loop/core/prompt.py")
    for rule_id, keywords in _RULE_KEYWORDS.items():
        # 长规则（多子规则/多要素/加长总纲）用更大窗口；其余规则 600 字符
        window = (
            1600
            if rule_id
            in {
                "RULE-AI-00",
                "RULE-AI-06",
                "RULE-AI-07",
                "RULE-AI-08",
                "RULE-AI-09",
                "RULE-AI-10",
            }
            else 600
        )
        doc_section = doc[doc.find(rule_id) :][:window]
        prompt_section = prompt[prompt.find(rule_id) :][:window]
        for kw in keywords:
            assert kw in doc_section or kw in doc[: doc.find(rule_id) + 40], (
                f"ai_rules.md {rule_id} 缺关键词: {kw}"
            )
            assert kw in prompt_section or kw in prompt[: prompt.find(rule_id) + 40], (
                f"prompt.py {rule_id} 缺关键词: {kw}"
            )
