"""R8.24-B 6.3: "运行时故障零 prompt"静态断言.

五个退役提示函数（E15/E16/E18 决策与预警/E17 overflow 教程）不得存在任何
生产调用点（调用即红灯）——函数体仅在 honesty.py 保留历史参照与测试反例。
"""

from __future__ import annotations

from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "llm_loop"

_RETIRED_FUNCTIONS = (
    "max_iterations_decision_message",
    "max_iterations_warning_message",
    "stagnation_reminder_message",
    "empty_search_reminder_message",
    "overflow_feedback",
)


def _iter_py_files():
    yield from _SRC_ROOT.rglob("*.py")


def test_retired_prompt_functions_have_no_production_call_sites():
    """函数名只允许出现在 honesty.py（定义+docstring）；他处出现即红灯。"""
    violations: list[str] = []
    for path in _iter_py_files():
        if path.name == "honesty.py" and path.parent.name == "feedback":
            continue
        text = path.read_text(encoding="utf-8")
        for func in _RETIRED_FUNCTIONS:
            if func in text:
                violations.append(f"{path.relative_to(_SRC_ROOT)}: {func}")
    assert violations == [], f"退役函数生产调用点: {violations}"


def test_engine_no_longer_imports_retired_messages():
    """engine 主链不得 import 退役消息构造器（防复活的第一道门）。"""
    engine_src = (_SRC_ROOT / "core" / "loop" / "engine.py").read_text(encoding="utf-8")
    for func in _RETIRED_FUNCTIONS:
        assert func not in engine_src


def test_overflow_path_is_deterministic_runtime_control():
    """overflow 处理面零 prompt 语义: _handle_overflow 不构造任何 Message 注入.

    R9 B5-W1-02: 面迁至 engine_services/termination_controller.py（_OverflowMixin 退役），
    零注入断言跟随迁移（"budget_shrunk" 确定性收缩在场；终态纯事实文本在场；
    旧注入通道标识双缺席 = B-D5 零 prompt 注入面持续成立）。
    """
    overflow_src = (
        _SRC_ROOT / "core" / "loop" / "engine_services" / "termination_controller.py"
    ).read_text(encoding="utf-8")
    assert "overflow_feedback" not in overflow_src
    assert "render_program_appendix" not in overflow_src
    assert "budget_shrunk" in overflow_src  # 确定性收缩在场
    assert "[上下文超限]" in overflow_src  # B-G3 纯事实终态文本在场


def test_stagnation_reminder_is_event_only():
    """停滞/空搜索提醒: tool_exec 提醒路径零 Message 构造（事件观测替代）。"""
    tool_exec_src = (_SRC_ROOT / "core" / "loop" / "tool_exec.py").read_text(encoding="utf-8")
    assert "stagnation_reminder_message" not in tool_exec_src
    assert "empty_search_reminder_message" not in tool_exec_src
    assert "stagnation.reminder" in tool_exec_src  # 事件通道在场
    assert "empty_search.reminder" in tool_exec_src


def test_program_final_boundary_is_protocol_only():
    """B-D11/B-G9: 占位为 neutral ASCII 协议形状，中文语义标签退役。"""
    from llm_loop.core.prompt_eligibility import PROGRAM_FINAL_PROTOCOL_BOUNDARY

    assert PROGRAM_FINAL_PROTOCOL_BOUNDARY == "[program-final]"
    assert "[程序终止边界" not in PROGRAM_FINAL_PROTOCOL_BOUNDARY
