"""Codex 风格 Skills 工具测试（2026-08-13 头条文章盘点补齐）."""

from unittest.mock import MagicMock

from llm_loop.core.message import ToolResultStatus
from llm_loop.introspection.tools_skills import (
    CODE_REVIEW_TOOL_DEF,
    GRILL_ME_TOOL_DEF,
    STOP_SLOP_TOOL_DEF,
    run_code_review,
    run_grill_me,
    run_stop_slop,
)


def _ctx():
    return MagicMock()


def _audit():
    return MagicMock()


# ── code_review ──
def test_code_review_basic():
    r = run_code_review(_ctx(), _audit(), {"code": "def add(a, b):\n    return a + b\n", "language": "python"})
    assert r.status == ToolResultStatus.SUCCESS, r.content[:200]
    assert "审查报告" in r.content
    assert "审查维度清单" in r.content
    assert "代码异味扫描" in r.content
    assert "未发现常见代码异味" in r.content  # 这个无异味
    print("✅ test_code_review_basic")


def test_code_review_smell():
    r = run_code_review(_ctx(), _audit(), {"code": "password = 'secret123'\neval(user_input)\n", "language": "python"})
    assert r.status == ToolResultStatus.SUCCESS
    assert "疑似密码硬编码" in r.content
    assert "使用 eval()" in r.content
    print("✅ test_code_review_smell")


def test_code_review_focus_filter():
    r = run_code_review(_ctx(), _audit(), {
        "code": "x = 1\n",
        "focus": ["security", "performance"],
    })
    assert r.status == ToolResultStatus.SUCCESS
    assert "security" in r.content
    assert "performance" in r.content
    # correctness 不应在内容里（被过滤）
    assert "correctness" not in r.content.split("审查维度清单")[1].split("##")[0]
    print("✅ test_code_review_focus_filter")


def test_code_review_empty_code():
    r = run_code_review(_ctx(), _audit(), {"code": ""})
    assert r.status == ToolResultStatus.FAILURE
    assert "code 为空" in r.content
    print("✅ test_code_review_empty_code")


def test_code_review_bad_focus():
    r = run_code_review(_ctx(), _audit(), {"code": "x = 1", "focus": "not_list"})
    assert r.status == ToolResultStatus.FAILURE
    assert "focus 需为数组" in r.content
    print("✅ test_code_review_bad_focus")


# ── grill_me ──
def test_grill_me_basic():
    r = run_grill_me(_ctx(), _audit(), {"design": "做一个用户登录系统，POST /login 校验账号密码"})
    assert r.status == ToolResultStatus.SUCCESS
    assert "追问式设计评审" in r.content
    assert "第一层" in r.content
    assert "edge_cases" in r.content
    assert "failure_modes" in r.content
    assert "security" in r.content
    print("✅ test_grill_me_basic")


def test_grill_me_depth():
    r = run_grill_me(_ctx(), _audit(), {"design": "做缓存", "depth": 5})
    assert r.status == ToolResultStatus.SUCCESS
    assert "第 5 层" in r.content
    print("✅ test_grill_me_depth")


def test_grill_me_focus_areas():
    r = run_grill_me(_ctx(), _audit(), {
        "design": "做缓存",
        "focus_areas": ["security", "scale"],
    })
    assert r.status == ToolResultStatus.SUCCESS
    # 只应显示 security 和 scale（没 edge_cases）
    sec = r.content.count("edge_cases")
    assert sec == 0  # 仅在禁用列表里
    print("✅ test_grill_me_focus_areas")


def test_grill_me_empty_design():
    r = run_grill_me(_ctx(), _audit(), {"design": ""})
    assert r.status == ToolResultStatus.FAILURE
    assert "design 为空" in r.content
    print("✅ test_grill_me_empty_design")


# ── stop_slop ──
def test_stop_slop_clean_text():
    r = run_stop_slop(_ctx(), _audit(), {"text": "用户输入密码错误，请重新输入。"})
    assert r.status == ToolResultStatus.SUCCESS
    assert "未发现典型 AI 味" in r.content
    print("✅ test_stop_slop_clean_text")


def test_stop_slop_detects_slop():
    r = run_stop_slop(_ctx(), _audit(), {
        "text": "首先，我们需要考虑这个方案；其次，它至关重要；最后，让我们一起完成。",
    })
    assert r.status == ToolResultStatus.SUCCESS
    assert "AI 味" in r.content or "AI味" in r.content
    assert "首先" in r.content or "模板化" in r.content
    print("✅ test_stop_slop_detects_slop")


def test_stop_slop_aggressive():
    r = run_stop_slop(_ctx(), _audit(), {
        "text": "首先，这是个测试。最后，完成。",
        "aggressive": True,
    })
    assert r.status == ToolResultStatus.SUCCESS
    assert "清洗后文本" in r.content
    print("✅ test_stop_slop_aggressive")


def test_stop_slop_empty():
    r = run_stop_slop(_ctx(), _audit(), {"text": ""})
    assert r.status == ToolResultStatus.FAILURE
    assert "text 为空" in r.content
    print("✅ test_stop_slop_empty")


# ── 工具定义 schema 完整性 ──
def test_tool_defs_have_required_fields():
    for name, defn in [("code_review", CODE_REVIEW_TOOL_DEF),
                       ("grill_me", GRILL_ME_TOOL_DEF),
                       ("stop_slop", STOP_SLOP_TOOL_DEF)]:
        assert "name" in defn and defn["name"] == name
        assert "description" in defn
        assert "parameters" in defn
        params = defn["parameters"]
        assert params["type"] == "object"
        assert "properties" in params
        # 每个 required field 必须在 properties 里
        for req in params.get("required", []):
            assert req in params["properties"], f"{name} 缺 required {req}"
        print(f"  ✅ {name} schema 完整")


if __name__ == "__main__":
    test_code_review_basic()
    test_code_review_smell()
    test_code_review_focus_filter()
    test_code_review_empty_code()
    test_code_review_bad_focus()
    test_grill_me_basic()
    test_grill_me_depth()
    test_grill_me_focus_areas()
    test_grill_me_empty_design()
    test_stop_slop_clean_text()
    test_stop_slop_detects_slop()
    test_stop_slop_aggressive()
    test_stop_slop_empty()
    test_tool_defs_have_required_fields()
    print("\n🎉 全部 Skills 测试通过 (13/13)")
