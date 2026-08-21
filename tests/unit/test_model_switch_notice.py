"""2026-08-20（镜像, DESIGN-v3 v2 落地）: 模型切换通知注入——AI 主导上下文选择第一步.

验证 _inject_switch_notice 真实方法:
- 切换时填充 _tip_tail_messages（build 消费、尾部追加、转 user、一次性）
- 同模型不注入（零回归）
- 注入内容含动作选项（search_archive）
"""
from __future__ import annotations

from llm_loop.core.loop.engine import LoopEngine


def _engine() -> LoopEngine:
    """最小 engine 实例（仅测注入方法，不装配完整循环）."""
    eng = object.__new__(LoopEngine)
    eng._tip_tail_messages = None
    return eng


def test_switch_notice_filled_on_model_change():
    eng = _engine()
    eng._inject_switch_notice("deepseek/deepseek-v4-flash", "minimax/MiniMax-M3")
    tips = eng._tip_tail_messages
    assert tips is not None and len(tips) == 1
    assert tips[0].role == "system"
    assert "模型切换感知" in tips[0].content
    assert "deepseek/deepseek-v4-flash" in tips[0].content
    assert "minimax/MiniMax-M3" in tips[0].content
    assert "search_archive" in tips[0].content  # AI 动作选项
    assert tips[0].metadata.get("injected_system") is True


def test_switch_notice_noop_same_model():
    eng = _engine()
    eng._inject_switch_notice("deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-flash")
    assert eng._tip_tail_messages is None  # 同模型不注入


def test_switch_notice_accumulates_multiple():
    """连续多次切换（工具循环内）→ 通知累加（各次切换各自感知）."""
    eng = _engine()
    eng._inject_switch_notice("deepseek/deepseek-v4-flash", "minimax/MiniMax-M3")
    eng._inject_switch_notice("minimax/MiniMax-M3", "deepseek/deepseek-v4-flash")
    tips = eng._tip_tail_messages
    assert tips is not None and len(tips) == 2
    assert "minimax/MiniMax-M3" in tips[0].content
    assert "deepseek/deepseek-v4-flash" in tips[1].content


def test_switch_notice_empty_from_noop():
    eng = _engine()
    eng._inject_switch_notice("", "minimax/MiniMax-M3")
    assert eng._tip_tail_messages is None
