"""声明-回执校验器未覆盖分支回归锁定（2026-10-23，行级 trace 探针驱动）.

缺口发现方法（非猜测）: 对 `src/llm_loop/feedback/validator.py` 跑行级 trace
探针（sys.settrace 记录执行行 ∩ ast 语句行集合），先跑完仓库现有 8 个
validator 测试文件（实测 76 passed），差集给出**从未被执行**的分支：

| 分支 | 语义 | 现有覆盖实况 |
|------|------|--------------|
| L410-411 | 疑问后缀豁免（"命令执行了吗"） | 无——该句天然含完成标志"了"，缺此分支即成假阳性 |
| L429-430 | 枚举选项句豁免（①②③） | 形似但被更早分支拦截（"决策"叙事词），本分支未被触达 |
| L431-432 | 判断/结论句豁免（"结论：…成立"） | 形似但实际走名词化吸收分支（L421-424），本分支未被触达 |
| L629-630 | 语义匹配命中（score ≥ threshold） | 无——既有 semantic 用例被路径 token 关键词短路，语义分支从未执行 |
| L332 | 同句去重（重复声明只报一次） | 无 |

本文件只锁定既有语义，不改实现、不放宽断言：每条用例都断言分支的**业务
含义**（豁免 / 命中 / 去重方向），豁免类分支一律配"反例对照"（含完成标志
的真完成声明仍必须被抽取），防豁免通道被改回误报方向而无人察觉。
"""

from __future__ import annotations

import json

from llm_loop.core.message import Message, MessageSource, ToolResultStatus
from llm_loop.feedback.validator import DeclarationValidator


def _extract(answer: str) -> list[str]:
    """抽取完成声明（不传 audit_dir → 无落盘副作用）."""
    return DeclarationValidator()._extract_declarations(answer)


def _tool_msg(content: str, tool_name: str = "read_file") -> Message:
    return Message(
        role="tool",
        content=content,
        source=MessageSource.TOOL,
        tool_call_id="c1",
        status=ToolResultStatus.SUCCESS,
        tool_name=tool_name,
    )


# ── L410-411: 疑问后缀豁免 ──


def test_question_suffix_sentence_is_not_a_completion_claim():
    """征询句不是完成声明: "命令执行了吗"是提问，不该被要求回执佐证.

    该句天然含完成标志"了"——若无本分支，会被完成标志门判为真完成声明并
    索要成功回执（假阳性），逼 LLM 为一句提问认领不存在的执行事实。
    """
    assert _extract("命令执行了吗") == [], "疑问句不得被抽为完成声明"


def test_completion_statement_without_question_suffix_still_checked():
    """反例对照: 去掉疑问后缀即恢复为完成声明，必须保留校验（防豁免过宽）."""
    assert _extract("命令执行了"), "完成态陈述必须保留校验"


# ── L429-430: 枚举选项句豁免 ──


def test_enum_option_sentence_is_exempt():
    """枚举选项句豁免: "① 删除旧文件 ② 更新索引"列的是待选项，不是自身已完成动作."""
    assert _extract("① 删除旧文件 ② 更新索引") == [], "枚举选项句应豁免"


def test_enum_option_with_completion_marker_still_checked():
    """反例对照: 含完成标志的枚举句仍必须被抽取（豁免通道不得变成逃逸路径）."""
    decls = _extract("① 已删除旧文件 ② 已更新索引")
    assert decls, "含完成标志的真完成声明不得被枚举豁免漏检"


# ── L431-432: 判断/结论句豁免 ──


def test_judgment_conclusion_sentence_is_exempt():
    """判断/结论句豁免: 对结论的评述不是自身动作声明，无需回执佐证."""
    assert _extract("结论：本次执行的方案判断全部成立") == [], "结论句应豁免"


# ── L629-630: 语义匹配命中路径（FR-P1-OPT-01）──


def test_semantic_matcher_hit_is_recorded_as_semantic(tmp_path):
    """关键词未命中时由语义分数判定一致，且命中方式必须记为 semantic.

    既有 semantic 用例实际被路径 token 关键词短路（其 docstring 自述"路径
    token 即命中 keyword"），语义分支从未执行——本用例用"无路径 token、
    无动词字面重合"的声明+回执强制走语义分支，并以审计 matched_by 取证。
    """
    validator = DeclarationValidator(
        audit_dir=tmp_path / "audit",
        semantic_matcher=lambda _decl, _receipt: 0.99,
        semantic_threshold=0.75,
    )
    result = validator.check("我已执行了这项校验", [_tool_msg("notes 校验通过")])
    assert result.consistent is True, f"语义分数达阈值应判一致: {result.discrepancies}"

    log = tmp_path / "audit" / "declaration_check.jsonl"
    rows = [
        json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert rows[-1]["matched_by"] == ["semantic"], (
        "命中方式必须记为 semantic（证明确实走了语义分支而非关键词短路）"
    )


def test_semantic_matcher_below_threshold_stays_inconsistent():
    """语义分数低于阈值不得判一致（不伪造一致）."""
    validator = DeclarationValidator(
        semantic_matcher=lambda _decl, _receipt: 0.2,
        semantic_threshold=0.75,
    )
    result = validator.check("我已执行了这项校验", [_tool_msg("notes 校验通过")])
    assert result.consistent is False, "语义分数未达阈值必须判不一致"
    assert result.discrepancies, "不一致须给出差异说明"


# ── L332: 同句去重 ──


def test_duplicate_declaration_sentence_is_deduplicated():
    """同一句重复出现只计一次声明（不重复报差异）."""
    decls = _extract("已写入 src/a.py。已写入 src/a.py。")
    assert len(decls) == 1, f"重复句应去重，实际: {decls}"
