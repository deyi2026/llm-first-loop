"""2026-08-20（镜像）: cache_health 模型切换归因——跨端交替模型时不再误报锚点漂移."""

from __future__ import annotations

from llm_loop.core.cache_health import CacheHealthMonitor


def test_model_switch_resets_window_with_honest_note():
    """模型切换 → 窗口重置 + 归因提示（新模型无前缀, 非漂移）."""
    m = CacheHealthMonitor(min_runs=2, min_tokens=1000)
    # minimax 正常轮次
    assert m.record(100000, 98000, model_ref="minimax/MiniMax-M3") is None
    # 切到 deepseek（如飞书轮次 fallback）→ 归因提示 + 窗口重置
    hint = m.record(100000, 5000, model_ref="deepseek/deepseek-v4-flash")
    assert hint is not None
    assert "模型切换" in hint and "独立预热" in hint and "非前缀漂移" in hint
    # 窗口已重置: 新模型第二轮才算窗口（低命中不触发锚点告警）
    assert m._win_runs == 1  # 仅切后第一轮计入


def test_model_switch_not_reported_as_anchor_break():
    """切换后的低命中不触发"锚点前移破坏"告警/拦截."""
    m = CacheHealthMonitor(min_runs=2, min_tokens=1000)
    m.record(100000, 98000, model_ref="minimax/MiniMax-M3")
    # 切到 deepseek 后连续低命中
    m.record(100000, 0, model_ref="deepseek/deepseek-v4-flash")
    assert m._alerted is False  # 未被误判为破坏型 → 未拦截
    assert m._force_head_keep is False


def test_same_model_continuous_no_reset():
    """同一模型连续轮次不重置（正常累积窗口）."""
    m = CacheHealthMonitor(min_runs=2, min_tokens=1000)
    m.record(100000, 98000, model_ref="minimax/MiniMax-M3")
    m.record(100000, 97000, model_ref="minimax/MiniMax-M3")
    assert m._win_runs == 2  # 未重置, 正常累积
