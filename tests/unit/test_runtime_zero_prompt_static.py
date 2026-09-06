"""R8.24-B 6.3: "运行时故障零 prompt"静态断言.

五个退役提示生产者（E15/E16/E18 决策与预警/E17 overflow 教程）不得存在于
生产源码。历史语义由 Git/测试场景留存，不在 runtime 养无调用函数。
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


def test_retired_prompt_producers_are_absent_from_production_source():
    """Rule-first: retired strategy-prose producers do not remain as dead runtime APIs."""
    violations: list[str] = []
    for path in _iter_py_files():
        text = path.read_text(encoding="utf-8")
        for func in _RETIRED_FUNCTIONS:
            if f"def {func}(" in text or f"import {func}" in text:
                violations.append(f"{path.relative_to(_SRC_ROOT)}: {func}")
    assert violations == [], f"退役 prompt producer 仍在生产源码: {violations}"


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


def test_repeat_and_empty_search_are_event_only():
    """P2-A: repeat/empty-search telemetry is event-only and cannot create model messages."""
    tool_cycle_src = (
        _SRC_ROOT / "core" / "loop" / "engine_services" / "tool_cycle.py"
    ).read_text(encoding="utf-8")
    assert "stagnation_reminder_message" not in tool_cycle_src
    assert "empty_search_reminder_message" not in tool_cycle_src
    assert "tool.repeat_observed" in tool_cycle_src
    assert "tool.empty_search_observed" in tool_cycle_src
    assert "stagnation.break" not in tool_cycle_src


def test_program_final_boundary_is_protocol_only():
    """B-D11/B-G9: role boundary carries zero model-visible control tokens."""
    from llm_loop.core.prompt_eligibility import (
        LEGACY_PROGRAM_FINAL_MARKER,
        PROGRAM_FINAL_PROTOCOL_BOUNDARY,
    )

    assert PROGRAM_FINAL_PROTOCOL_BOUNDARY == ""
    assert LEGACY_PROGRAM_FINAL_MARKER == "[program-final]"
