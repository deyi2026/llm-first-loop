"""task_quality 数据模型测试（design §2.3，frozen + 反馈方法 + 五态对齐）."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from llm_loop.task_quality import models as tq_models
from llm_loop.task_quality.models import (
    CheckerResult,
    CheckerStatus,
    CheckIssue,
    CheckOverallStatus,
    ConventionItem,
    ConventionSummary,
    ConventionType,
    DepEdge,
    DepNode,
    DepNodeType,
    DepRelation,
    ErrorLocationResult,
    FailureInfo,
    FieldError,
    FixLoopFinalStatus,
    FixLoopRecord,
    PreCheckResult,
    RegressionResult,
    RoundRecord,
    Severity,
    StaticCheckResult,
)


def test_precheck_guidance_feedback_valid():
    """预检通过: 反馈'通过'."""
    r = PreCheckResult(valid=True)
    assert "[参数预检] 通过" in r.to_guidance_feedback()


def test_precheck_guidance_feedback_field_error():
    """预检失败: 字段级错误引导（嵌套路径/类型/问题）."""
    r = PreCheckResult(
        valid=False,
        errors=(
            FieldError("steps[2].executor", "str", "int", "executor 必须是字符串"),
            FieldError("timeout_s", "int", "str", "类型不匹配"),
        ),
    )
    text = r.to_guidance_feedback()
    assert "steps[2].executor" in text
    assert "expected str, got int" in text
    assert "timeout_s" in text
    assert "expected int, got str" in text
    assert "共 2 处" in text


def test_precheck_frozen():
    """frozen: 不可变."""
    r = PreCheckResult(valid=True)
    with pytest.raises(FrozenInstanceError):
        r.valid = False  # type: ignore[misc]


def test_static_check_feedback_success():
    """静态检查全过: SUCCESS."""
    r = StaticCheckResult(
        file_path="a.py", language="python",
        overall_status=CheckOverallStatus.SUCCESS,
        checkers=(CheckerResult("ruff", CheckerStatus.SUCCESS),),
    )
    text = r.to_feedback_section()
    assert "[状态: success]" in text
    assert "ruff" in text


def test_static_check_feedback_issues():
    """静态检查有 error: FAILURE + 清单（file:line:col/code/severity）."""
    r = StaticCheckResult(
        file_path="a.py", language="python",
        overall_status=CheckOverallStatus.FAILURE,
        checkers=(
            CheckerResult(
                "ruff", CheckerStatus.FAILURE,
                issues=(CheckIssue("a.py", 10, 3, "E501", "line too long", Severity.ERROR),),
            ),
        ),
    )
    text = r.to_feedback_section()
    assert "[状态: failure]" in text
    assert "a.py:10:3" in text
    assert "E501" in text
    assert "error" in text


def test_convention_injection_text():
    """约定注入文本: 类型标注 + 截断标注."""
    s = ConventionSummary(
        target_path="x.py",
        conventions=(
            ConventionItem(ConventionType.NAMING, "snake_case"),
            ConventionItem(ConventionType.TYPE_ANNOTATION, "强制类型标注"),
        ),
        source_files=("a.py", "b.py"),
        truncated=True, original_size=5000, retained_size=2000,
    )
    text = s.to_injection_text()
    assert "snake_case" in text
    assert "强制类型标注" in text
    assert "原始 5000 字符" in text
    assert "a.py" in text


def test_convention_empty_no_inject():
    """无约定: 不注入（空）."""
    s = ConventionSummary(target_path="x.py")
    assert s.to_injection_text() == ""


def test_error_location_fallback():
    """错误定位回退: 标注回退 + 原始输出."""
    r = ErrorLocationResult(
        framework=tq_models.TestFramework.UNKNOWN, fallback=True,
        original_output="raw output...", original_size=100, retained_size=100,
    )
    text = r.to_injection_text()
    assert "解析失败已回退" in text
    assert "raw output" in text


def test_error_location_structured():
    """错误定位结构化: 位置/原因/assert/代码片段."""
    r = ErrorLocationResult(
        framework=tq_models.TestFramework.PYTEST,
        failures=(FailureInfo("test_x.py", 5, "AssertionError", "assert x == 1", "x == 2"),),
    )
    text = r.to_injection_text()
    assert "test_x.py:5" in text
    assert "AssertionError" in text
    assert "x == 2" in text


def test_fix_loop_feedback_fuse():
    """修复循环熔断: 终态汇报含轮数/熔断原因/未修复项."""
    r = FixLoopRecord(
        loop_id="L1", trace_id="T1", max_rounds=5,
        rounds=(RoundRecord(1, "fail", "loc", "fix", "fail"), RoundRecord(2, "fail", "loc", "fix", "fail")),
        final_status=FixLoopFinalStatus.FUSE_TRIGGERED,
        unfixed_items=("E501: line too long",), fuse_count=3,
    )
    text = r.to_feedback_section()
    assert "[状态: fuse_triggered]" in text
    assert "2/5 轮" in text
    assert "连续 3 次" in text
    assert "E501" in text


def test_regression_feedback_subset():
    """回归保护子集: 范围/计数/失败详情."""
    r = RegressionResult(
        modified_files=("x.py",),
        affected_tests=("tests/test_x.py",),
        subset_ratio=0.5, passed_count=2, failed_count=1,
        failures=(FailureInfo("tests/test_x.py", 3, "assert failed"),),
        depgraph_available=True,
    )
    text = r.to_feedback_section()
    assert "受影响测试 1 个" in text
    assert "通过 2 / 失败 1" in text
    assert "tests/test_x.py:3" in text


def test_regression_no_affected():
    """无受影响测试: 标注不执行."""
    r = RegressionResult(modified_files=("README.md",), depgraph_available=True)
    text = r.to_feedback_section()
    assert "无受影响测试" in text


def test_dep_nodes_edges_frozen():
    """依赖图节点/边: frozen + 关系枚举."""
    n = DepNode(DepNodeType.MODULE, "m1", "src/a.py")
    e = DepEdge("m1", "t1", DepRelation.IMPORTED_BY)
    assert n.node_id == "m1"
    assert e.relation == DepRelation.IMPORTED_BY
    with pytest.raises(FrozenInstanceError):
        n.node_id = "hacked"  # type: ignore[misc]


def test_enum_str_values():
    """StrEnum: 值与 spec 对齐."""
    assert CheckOverallStatus.SUCCESS.value == "success"
    assert Severity.ERROR.value == "error"
    assert tq_models.TestFramework.PYTEST.value == "pytest"
    assert FixLoopFinalStatus.PASSED.value == "passed"
    assert ConventionType.NAMING.value == "naming"
    assert DepNodeType.TEST.value == "test"
