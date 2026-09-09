"""单元测试: 增长率 nudge 判定（_growth_nudge_kind, EVO-20260824-54d46549 镜像落地 2026-08-24）.

billion-context 拷问产出: 固定 80% 预警（每轮必警）→ 增长率门控双轨——
- 强制轨: 超预算×compact_ratio（90% 默认）→ 必警（压缩在即, bypass 增长率）
- 增长率轨: 80% 准备态 → 距上次预警增长 ≥ 阈值才预警（重任务早提示, 普通对话不打扰）
- 首轮基线（prev_total=None）→ 不警（无增长参照）

纯函数（无 self 依赖），直接测判定逻辑。
"""

from __future__ import annotations

from llm_loop.core.loop.build import _growth_nudge_kind


def test_force_track_over_compact_ratio():
    """超预算×compact_ratio（90%）→ 强制轨 'force'（bypass 增长率, 必警）."""
    # prev_total 很大也无所谓——force 不看增长率
    assert (
        _growth_nudge_kind(95000, 90000, prep_at=80000, force_at=90000, growth_floor=20000)
        == "force"
    )
    # prev_total=None（首轮）超限也 force
    assert (
        _growth_nudge_kind(95000, None, prep_at=80000, force_at=90000, growth_floor=20000)
        == "force"
    )


def test_growth_track_triggered():
    """80% 准备态 + 增长率达标 → 增长率轨 'growth'."""
    assert (
        _growth_nudge_kind(85000, 60000, prep_at=80000, force_at=90000, growth_floor=20000)
        == "growth"
    )
    # 增长率刚好等于 floor → 触发（>= 语义）
    assert (
        _growth_nudge_kind(85000, 65000, prep_at=80000, force_at=90000, growth_floor=20000)
        == "growth"
    )


def test_growth_track_not_triggered_slow_growth():
    """80% 准备态但增长率不足 → None（不警）——替换原固定 80% 每轮必警的关键."""
    assert (
        _growth_nudge_kind(82000, 80000, prep_at=80000, force_at=90000, growth_floor=20000) is None
    )
    # 增长为负/持平也不警
    assert (
        _growth_nudge_kind(80000, 85000, prep_at=80000, force_at=90000, growth_floor=20000) is None
    )


def test_first_round_baseline_no_nudge():
    """首轮（prev_total=None）→ None（建立基线, 不预警——无增长参照）."""
    assert (
        _growth_nudge_kind(85000, None, prep_at=80000, force_at=90000, growth_floor=20000) is None
    )


def test_below_prep_at_no_nudge():
    """未到 80% 准备态 → None（不管增长率多大）."""
    assert (
        _growth_nudge_kind(70000, 10000, prep_at=80000, force_at=90000, growth_floor=20000) is None
    )
    assert (
        _growth_nudge_kind(70000, None, prep_at=80000, force_at=90000, growth_floor=20000) is None
    )
