"""方向 B 决策点复扫守护测试（spec 5.1 / design §2.4.1 / tasks 2.1）.

守护目标: 把 round4 方向 B 核验结论（五类候选全部合规保留、无可移交项）固化为静态断言，
防止未来「程序替 AI 决策」退化（自动摘要注入上下文、自动切换、自动调整参数等形态）。

断言:
1. 基线文档含「非 if-return 决策点复扫」结论 + 五类候选名
2. 基线文档含「无可移交项」/「全部合规保留」表述
3. 基线文档含「硬边界保留声明」+ 关键词
4. 基线文档含分类归属（硬边界/仅提示/执行通道/视图）
5. if-return 度量项保持 AST 精确口径（ai_decision=0）
6. _adaptive_tool_trim_age 保持「待后续评估」标注
7. grep 复核源码：五类决策点仍属合规形态（无替 AI 决策退化）
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "ANALYSIS-20260813-program-complexity-baseline.md"
SRC = ROOT / "src" / "llm_loop"


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def baseline_src() -> str:
    return BASELINE.read_text(encoding="utf-8")


class TestDecisionScanConclusion:
    def test_five_candidates_listed(self, baseline_src: str):
        assert "非 if-return 决策点复扫" in baseline_src
        for name in ("自动摘要", "自动演进", "自动切换", "定期自评", "参数视图"):
            assert name in baseline_src

    def test_no_transferable_item(self, baseline_src: str):
        assert "无可移交项" in baseline_src
        assert "全部合规保留" in baseline_src

    def test_hard_boundary_preserved(self, baseline_src: str):
        assert "硬边界保留声明" in baseline_src
        for kw in ("输入校验", "并发安全", "FR-SAFE-01", "C1-C6"):
            assert kw in baseline_src

    def test_classification_attribution(self, baseline_src: str):
        for kw in ("硬边界", "仅提示", "执行通道", "视图"):
            assert kw in baseline_src

    def test_if_return_ast_caliber(self, baseline_src: str):
        assert "ai_decision" in baseline_src
        assert "AST 精确核验" in baseline_src

    def test_adaptive_tool_trim_age_pending(self, baseline_src: str):
        assert "_adaptive_tool_trim_age" in baseline_src
        assert "待后续评估" in baseline_src


class TestDecisionScanSourceGuard:
    """grep 复核源码：五类决策点仍属合规形态（守护程序最小化，spec 5.1 规则 7）."""

    def test_auto_summary_not_injected_to_context(self):
        # 自动摘要只回填档案、不注入消息流（反模式：messages.append 摘要到上下文）
        summarize = _read("src/llm_loop/memory/summarize.py")
        assert "update_summary" in summarize  # 回填档案
        assert "messages.append" not in summarize  # 不注入消息流

    def test_evolution_action_delegated_to_ai(self):
        evolution = _read("src/llm_loop/introspection/evolution_exec.py")
        assert "程序不代 AI 调用修正工具" in evolution  # 执行动作移交 AI

    def test_fallback_strict_mode(self):
        engine = _read("src/llm_loop/core/loop/engine.py")
        assert "is_default_assembled" in engine  # 仅默认装配才降级（严格模式）

    def test_runtime_no_auto_adjust(self):
        runtime = _read("src/llm_loop/core/runtime_params.py")
        assert "adjust_strategy" in runtime  # AI 触发调整
        assert "HARD_CAP_MAX_ITERATIONS" in runtime  # 硬上限（硬边界）
