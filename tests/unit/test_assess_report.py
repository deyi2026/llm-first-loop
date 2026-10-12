"""评估报告生成器测试（spec.md §5.1 / design.md §2.5 / tasks.md T1.6）.

断言:
1. 四维扫描器返回结构合法（str + list[HiddenRisk]，每条隐患附证据）
2. RULE-AI-00 对照含六原则
3. 优先级排序合法（P0 ≤ P1 ≤ P2）
4. 可移交清单字段完整
5. 报告四维章节齐全 + kebab-case 命名
6. 报告不含实现方案细节（无类图/接口签名/代码块）
7. 报告脱敏（不含 api_key 字面量）
8. 证据缺失场景如实标注"证据待补"不阻塞
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parents[2]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))
for _k in [k for k in _sys.modules if k == "scripts" or k.startswith("scripts.")]:
    del _sys.modules[_k]

import pytest  # noqa: E402 — sys.path 注入必须在前

from scripts.assess_ai_first_evolution import (  # noqa: E402 — sys.path 注入必须在前
    DIMENSIONS,
    RULE_AI_00_PRINCIPLES,
    AssessmentReport,
    HiddenRisk,
    RuleAI00Check,
    TransferableItem,
    check_rule_ai_00,
    extract_transferable,
    prioritize,
    run_assessment,
    scan_ai_friendliness,
    scan_content_display,
    scan_elegance,
    scan_robustness,
    write_report,
)


@pytest.fixture
def all_risks() -> list[HiddenRisk]:
    risks: list[HiddenRisk] = []
    for scan in [scan_robustness, scan_elegance, scan_ai_friendliness, scan_content_display]:
        _, r = scan()
        risks.extend(r)
    return risks


class TestFourScanners:
    def test_robustness_returns_conclusion_and_risks(self):
        concl, risks = scan_robustness()
        assert isinstance(concl, str) and len(concl) > 0
        assert isinstance(risks, list)
        for r in risks:
            assert r.dimension == "健壮性"
            assert r.evidence and ":" in r.evidence

    def test_elegance_returns_conclusion_and_risks(self):
        concl, risks = scan_elegance()
        assert isinstance(concl, str) and len(concl) > 0
        for r in risks:
            assert r.dimension == "优雅性"
            assert r.evidence

    def test_ai_friendliness_returns_conclusion_and_risks(self):
        concl, risks = scan_ai_friendliness()
        assert isinstance(concl, str) and len(concl) > 0
        for r in risks:
            assert r.dimension == "AI 友好性"
            assert r.evidence

    def test_content_display_returns_conclusion_and_risks(self):
        concl, risks = scan_content_display()
        assert isinstance(concl, str) and len(concl) > 0
        for r in risks:
            assert r.dimension == "内容显示"
            assert r.evidence

    def test_all_four_dimensions_present(self):
        scanners = {
            "健壮性": scan_robustness,
            "优雅性": scan_elegance,
            "AI 友好性": scan_ai_friendliness,
            "内容显示": scan_content_display,
        }
        assert set(scanners.keys()) == set(DIMENSIONS)


class TestRuleAI00Check:
    def test_six_principles(self, all_risks):
        check = check_rule_ai_00(all_risks)
        assert isinstance(check, RuleAI00Check)
        assert len(check.principles) == 6
        assert len(RULE_AI_00_PRINCIPLES) == 6

    def test_principle_statuses_valid(self, all_risks):
        check = check_rule_ai_00(all_risks)
        for p in check.principles:
            assert p.status in {"VIOLATES", "COMPLIES", "UNRELATED"}
            assert p.pid and p.name and p.statement

    def test_violating_risks_referenced_exist(self, all_risks):
        check = check_rule_ai_00(all_risks)
        risk_ids = {r.id for r in all_risks}
        for p in check.principles:
            for vid in p.violating_risks:
                assert vid in risk_ids


class TestPrioritize:
    def test_sorted_by_priority(self, all_risks):
        ordered = prioritize(all_risks)
        order = {"P0": 0, "P1": 1, "P2": 2}
        for i in range(len(ordered) - 1):
            assert order[ordered[i].priority] <= order[ordered[i + 1].priority]

    def test_preserves_all_risks(self, all_risks):
        ordered = prioritize(all_risks)
        assert len(ordered) == len(all_risks)

    def test_priority_values_valid(self, all_risks):
        for r in all_risks:
            assert r.priority in {"P0", "P1", "P2"}


class TestExtractTransferable:
    def test_fields_complete(self, all_risks):
        transferable = extract_transferable(all_risks)
        for t in transferable:
            assert isinstance(t, TransferableItem)
            assert t.id and t.program_location and t.suggested_rule
            assert t.acceptance_criteria and t.priority in {"P0", "P1", "P2"}

    def test_only_ai_friendliness_violations(self, all_risks):
        transferable = extract_transferable(all_risks)
        viol_ids = {r.id for r in all_risks if r.rule_ai_00 == "VIOLATES" and r.dimension == "AI 友好性"}
        assert len(transferable) == len(viol_ids)


class TestWriteReport:
    @pytest.fixture
    def report(self, all_risks) -> AssessmentReport:
        rule_check = check_rule_ai_00(all_risks)
        return AssessmentReport(
            date="20260813",
            dimensions={d: f"{d} 测试结论" for d in DIMENSIONS},
            risks=all_risks,
            rule_check=rule_check,
            transferable=extract_transferable(all_risks),
            next_steps=["测试建议 1", "测试建议 2"],
        )

    def test_report_file_created_kebab_case(self, tmp_path, report):
        path = write_report(report, tmp_path)
        assert path.exists()
        assert path.name == "ASSESSMENT-20260813-ai-first-evolution.md"

    def test_four_dimension_sections_present(self, tmp_path, report):
        path = write_report(report, tmp_path)
        content = path.read_text(encoding="utf-8")
        for dim in DIMENSIONS:
            assert f"### {dim}" in content

    def test_rule_ai_00_table_present(self, tmp_path, report):
        path = write_report(report, tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "## 二、RULE-AI-00 六原则对照" in content
        for pid, _name, _ in RULE_AI_00_PRINCIPLES:
            assert pid in content

    def test_priority_table_present(self, tmp_path, report):
        path = write_report(report, tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "## 三、隐患优先级排序" in content

    def test_transferable_section_present(self, tmp_path, report):
        path = write_report(report, tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "## 四、可移交清单" in content

    def test_next_steps_present(self, tmp_path, report):
        path = write_report(report, tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "## 五、下一步建议" in content

    def test_no_implementation_details(self, tmp_path, report):
        path = write_report(report, tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "```python" not in content
        assert "```typescript" not in content
        assert "## 类图" not in content
        assert "## 接口设计" not in content

    def test_redacted_no_api_key_literal(self, tmp_path, report):
        path = write_report(report, tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "sk-1234567890" not in content
        assert "api_key=secretvalue" not in content

    def test_evidence_pending_note_present(self, tmp_path, report):
        path = write_report(report, tmp_path)
        content = path.read_text(encoding="utf-8")
        assert "证据待补" in content
        assert "维度边界声明" in content


class TestRunAssessment:
    def test_full_run_produces_report(self, tmp_path, monkeypatch):
        calls: list[str] = []
        monkeypatch.setattr(
            "scripts.assess_ai_first_evolution.update_index",
            lambda *a, **kw: calls.append("index"),
        )
        report = run_assessment(tmp_path, "20260813")
        assert isinstance(report, AssessmentReport)
        assert set(report.dimensions.keys()) == set(DIMENSIONS)
        assert len(report.rule_check.principles) == 6
        report_file = tmp_path / "ASSESSMENT-20260813-ai-first-evolution.md"
        assert report_file.exists()
