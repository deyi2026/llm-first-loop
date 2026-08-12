"""复杂度基线修正测试（spec 5.4 / design §2.4.5 / tasks 5.2）.

断言:
1. 基线文档含 AST 精确核验结论（ai_decision = 0）
2. 不再将 if.*return 6 处列为可移交候选
3. 含统计口径修正说明（grep 误匹配 returncode/三元 → AST 精确）
4. 含 except:pass 现状更新（14 清理 + 163 合规保留）
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "ANALYSIS-20260813-program-complexity-baseline.md"


@pytest.fixture(scope="module")
def baseline_src() -> str:
    return BASELINE.read_text(encoding="utf-8")


class TestComplexityBaseline:
    def test_ast_precise_conclusion(self, baseline_src: str):
        assert "AST 精确核验" in baseline_src
        assert "ai_decision" in baseline_src
        assert "无可移交项" in baseline_src

    def test_no_if_return_six_as_transferable(self, baseline_src: str):
        # 不再将 grep `if.*return` 6 处列为可移交候选
        assert "`if.*return` 6 处" not in baseline_src

    def test_statistical_caliber_correction(self, baseline_src: str):
        assert "口径修正" in baseline_src
        assert "returncode" in baseline_src
        assert "三元表达式" in baseline_src

    def test_except_pass_status_updated(self, baseline_src: str):
        assert "14" in baseline_src
        assert "163" in baseline_src
        assert "合规" in baseline_src
