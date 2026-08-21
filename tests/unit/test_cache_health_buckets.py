"""2026-08-20（镜像，EVO-20260820-0b96348d 镜像检验）: cache_health 按模型分桶 + 双口径展示.

覆盖新增能力（既有 3 个模型切换测试锁定"活动窗口切换即重置"语义不变）:
1. 每轮累计进当前模型桶（跨切换持久）
2. 切回热检查: 旧桶 hit>0 且 runs≥2 → 提示"仍热可继续累加"，不清零
3. 双口径展示: format_health_note 含"近 N 轮" + "本模型累计"
4. reset() 清桶（会话变更=全新统计面）
"""

from __future__ import annotations

from llm_loop.core.cache_health import CacheHealthMonitor


def test_bucket_accumulates_per_model_across_switch():
    """每轮累计进当前模型桶，切换不丢旧桶数据."""
    m = CacheHealthMonitor(min_runs=2, min_tokens=1000)
    m.record(100000, 98000, model_ref="minimax/MiniMax-M3")
    m.record(100000, 97000, model_ref="minimax/MiniMax-M3")
    m.record(100000, 5000, model_ref="deepseek/deepseek-v4-flash")
    # minimax 桶应保留两轮累计（不因切换丢失）
    b = m._buckets["minimax/MiniMax-M3"]
    assert b["runs"] == 2
    assert b["in"] == 200000
    assert b["hit"] == 195000
    # deepseek 桶独立
    b2 = m._buckets["deepseek/deepseek-v4-flash"]
    assert b2["runs"] == 1
    assert b2["hit"] == 5000


def test_switch_back_hot_bucket_note():
    """切回旧模型且旧桶仍热（hit>0, runs≥2）→ 提示可继续累加而非从头预热."""
    m = CacheHealthMonitor(min_runs=2, min_tokens=1000)
    m.record(100000, 98000, model_ref="minimax/MiniMax-M3")
    m.record(100000, 97000, model_ref="minimax/MiniMax-M3")
    # 切走再切回
    m.record(100000, 5000, model_ref="deepseek/deepseek-v4-flash")
    hint = m.record(100000, 96000, model_ref="minimax/MiniMax-M3")
    assert hint is not None
    assert "模型切换" in hint
    assert "仍热" in hint and "继续累加" in hint


def test_switch_cold_bucket_normal_note():
    """切回旧模型但旧桶冷（无命中/轮次不足）→ 常规提示（无"仍热"）."""
    m = CacheHealthMonitor(min_runs=2, min_tokens=1000)
    m.record(100000, 0, model_ref="minimax/MiniMax-M3")
    m.record(100000, 5000, model_ref="deepseek/deepseek-v4-flash")
    hint = m.record(100000, 96000, model_ref="minimax/MiniMax-M3")
    assert hint is not None
    assert "模型切换" in hint
    assert "仍热" not in hint


def test_format_health_note_dual_metric():
    """双口径展示: 近 N 轮 + 本模型累计."""
    m = CacheHealthMonitor(min_runs=2, min_tokens=1000)
    m.record(100000, 98000, model_ref="minimax/MiniMax-M3")
    m.record(100000, 97000, model_ref="minimax/MiniMax-M3")
    note = m.format_health_note()
    assert note is not None
    assert "近 2 轮" in note
    assert "本模型(" in note and "累计" in note
    # 本模型累计口径应含 minimax 桶数据
    assert "MiniMax" in note or "minimax" in note


def test_reset_clears_buckets():
    """reset()（会话变更）清空模型桶."""
    m = CacheHealthMonitor(min_runs=2, min_tokens=1000)
    m.record(100000, 98000, model_ref="minimax/MiniMax-M3")
    assert m._buckets
    m.reset(reason="会话变更")
    assert m._buckets == {}


def test_snapshot_includes_buckets():
    """snapshot 暴露模型桶（可观测/架构状态）."""
    m = CacheHealthMonitor(min_runs=2, min_tokens=1000)
    m.record(100000, 98000, model_ref="minimax/MiniMax-M3")
    snap = m.snapshot()
    assert "buckets" in snap
    assert snap["buckets"]["minimax/MiniMax-M3"]["runs"] == 1


def test_note_new_session_keeps_buckets():
    """新会话首轮（note_new_session）保留模型桶，只重置窗口与游标（用户决策）."""
    m = CacheHealthMonitor(min_runs=2, min_tokens=1000)
    m.record(100000, 98000, model_ref="minimax/MiniMax-M3")
    m.record(100000, 97000, model_ref="minimax/MiniMax-M3")
    # 模拟新会话首轮
    m.note_new_session(session_id="new-session-1")
    assert m._buckets["minimax/MiniMax-M3"]["runs"] == 2  # 桶保留
    assert m._last_model_ref is None  # 游标复位
    assert m._win_runs == 0  # 窗口重置


def test_reset_default_clears_buckets():
    """reset() 默认（clear_buckets=True）清模型桶（显式重置语义）."""
    m = CacheHealthMonitor(min_runs=2, min_tokens=1000)
    m.record(100000, 98000, model_ref="minimax/MiniMax-M3")
    m.reset(reason="显式重置")
    assert m._buckets == {}


def test_reset_clear_buckets_false_keeps():
    """reset(clear_buckets=False) 保留桶（模型切换轻量重置）."""
    m = CacheHealthMonitor(min_runs=2, min_tokens=1000)
    m.record(100000, 98000, model_ref="minimax/MiniMax-M3")
    m.reset(reason="model_switch:x", clear_buckets=False)
    assert "minimax/MiniMax-M3" in m._buckets
