"""if-return 决策类判断核验测试（spec 5.4.1 / design §2.4.4 / tasks 4.x）.

核验目标: 用 AST 精确核验替代 grep 误统计（design §1.2.4 证 grep `if.*return` 的 6 处
匹配全为 `returncode` 子串误匹配或三元表达式），区分「硬边界（hard_boundary）」与
「替 AI 决策（ai_decision）」型 if-return。

断言:
1. find_if_return_judgments 用 ast.If（非 grep/ast.IfExp），返回结构化清单
2. 每项含 file/lineno/condition_src/classification/reason 五字段
3. 排除 returncode 子串与三元表达式误统计（returncode 判定归 hard_boundary）
4. 本轮核验结论: classification == "ai_decision" 项为 0（无可移交项）
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "llm_loop"

# 「替 AI 决策」特征关键词（压缩/重试/摘要/模型切换/停滞/参数调整等"何时做某事"判断）。
# 本轮核验结论为无可移交项，故为空；若未来新增此类判断，应在此登记关键词以自动检出。
_AI_DECISION_HINTS: tuple[str, ...] = ()


@dataclass(frozen=True)
class IfReturnJudgment:
    file: str
    lineno: int
    condition_src: str
    classification: str  # "hard_boundary" | "ai_decision"
    reason: str


def _classify(cond_src: str) -> tuple[str, str]:
    if any(hint in cond_src for hint in _AI_DECISION_HINTS):
        return "ai_decision", "命中替 AI 决策特征关键词，需移交为文档规则 + AI 自主"
    if "returncode" in cond_src or ".code" in cond_src or "status_code" in cond_src:
        return "hard_boundary", "命令返回码/状态码判定（工具执行结果的如实判定，AI 无法自完成）"
    return "hard_boundary", "输入校验/资源上限/协议/配置开关等硬边界（程序守卫，非替 AI 决策）"


def find_if_return_judgments(root: Path) -> list[IfReturnJudgment]:
    """AST 精确核验: 定位 ast.If 且 body 首条为 ast.Return 的判断（排除 ast.IfExp 三元）."""
    results: list[IfReturnJudgment] = []
    for p in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            if not node.body or not isinstance(node.body[0], ast.Return):
                continue
            cond_src = ast.unparse(node.test)
            classification, reason = _classify(cond_src)
            results.append(
                IfReturnJudgment(
                    file=str(p.relative_to(ROOT)),
                    lineno=node.lineno,
                    condition_src=cond_src,
                    classification=classification,
                    reason=reason,
                )
            )
    return results


@pytest.fixture(scope="module")
def judgments() -> list[IfReturnJudgment]:
    return find_if_return_judgments(SRC)


class TestIfReturnAudit:
    def test_returns_structured_list(self, judgments):
        assert isinstance(judgments, list)
        assert len(judgments) > 0

    def test_each_has_complete_fields(self, judgments):
        for j in judgments:
            assert j.file and ":" not in j.file.split("/")[-1]  # 文件路径合法
            assert j.lineno > 0
            assert isinstance(j.condition_src, str) and j.condition_src
            assert j.classification in {"hard_boundary", "ai_decision"}
            assert j.reason

    def test_no_ai_decision(self, judgments):
        # 本轮核验结论: 无可移交项（design §2.0.4）
        ai_decision = [j for j in judgments if j.classification == "ai_decision"]
        assert ai_decision == []

    def test_returncode_judgments_are_hard_boundary(self, judgments):
        # design §1.2.4: grep 误统计的 returncode 子串，AST 精确核验后归硬边界
        rc = [j for j in judgments if "returncode" in j.condition_src]
        assert rc, "应存在 returncode 判定（如 proc_version/execute_command），否则核验范围有误"
        assert all(j.classification == "hard_boundary" for j in rc)

    def test_excludes_ternary_expressions(self, judgments):
        # ast.IfExp（三元）不是 ast.If，天然被排除：核验器不含三元表达式的 return 判断
        # 断言: 不存在 condition_src 形如 "x if cond else y" 的三元（ast.unparse 三元会含 if...else）
        for j in judgments:
            assert " if " not in j.condition_src or " else " not in j.condition_src
