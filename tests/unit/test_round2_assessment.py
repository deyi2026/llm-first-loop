"""三方面评估归档测试（spec 5.5.1 / design §2.4.5 / tasks 5.3）.

断言:
1. 报告含三方面评估章节 + 隐患收敛清单 + 优先级 + 维度边界声明
2. 34 条隐患逐条标注收敛状态（已清理/合规保留/待处理）
3. 报告不含 api_key/token/secret 字面量
4. docs/INDEX.md 报告清单含 round2 条目
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs" / "ASSESSMENT-20260813-ai-first-evolution-round2.md"
INDEX = ROOT / "docs" / "INDEX.md"

# 开源说明（2026-08-14）: 评估报告为本地开发过程文档，开源仓库不含——缺失时跳过
pytestmark = pytest.mark.skipif(
    not REPORT.is_file(), reason="评估报告为本地开发过程文档，开源仓库不含"
)

RISK_IDS = (
    [f"ROB-SILENT-{i:03d}" for i in range(1, 21)]
    + [f"ELG-DEGRADE-{i:03d}" for i in range(1, 11)]
    + ["AIF-PENDING-001", "CD-COLLAPSE-001", "CD-THRESH-001", "CD-TRUNC-001"]
)


@pytest.fixture(scope="module")
def report_src() -> str:
    return REPORT.read_text(encoding="utf-8")


class TestRound2Assessment:
    def test_report_exists(self):
        assert REPORT.exists()

    def test_three_dimension_sections(self, report_src: str):
        assert "架构健壮性" in report_src
        assert "Web 内容显示" in report_src
        assert "AI 视角友好度" in report_src

    def test_convergence_section(self, report_src: str):
        assert "隐患收敛清单" in report_src
        assert "优先级" in report_src
        assert "维度边界声明" in report_src

    def test_all_34_risks_listed_with_status(self, report_src: str):
        for rid in RISK_IDS:
            assert rid in report_src, f"隐患 {rid} 未在收敛清单中"
        assert "已清理" in report_src
        assert "合规保留" in report_src
        assert "待处理" in report_src

    def test_redacted_no_secret_literals(self, report_src: str):
        assert "sk-" not in report_src
        assert "api_key=" not in report_src
        assert "secret=" not in report_src
        assert "password" not in report_src.lower()

    def test_no_implementation_details(self, report_src: str):
        assert "```python" not in report_src
        assert "```typescript" not in report_src


class TestIndexRegistration:
    def test_index_lists_round2(self):
        index_src = INDEX.read_text(encoding="utf-8")
        assert "ASSESSMENT-20260813-ai-first-evolution-round2.md" in index_src
