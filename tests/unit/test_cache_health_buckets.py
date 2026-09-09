"""2026-08-20（镜像，EVO-20260820-0b96348d 镜像检验）: cache_health 按模型分桶 + 双口径展示.

覆盖新增能力（既有 3 个模型切换测试锁定"活动窗口切换即重置"语义不变）:
1. 每轮累计进当前模型桶（跨切换持久）
2. 切回热检查: 旧桶 hit>0 且 runs≥2 → 提示"仍热可继续累加"，不清零
3. 双口径展示: format_health_note 含"近 N 轮" + "本模型累计"
4. reset() 清桶（会话变更=全新统计面）
"""

from __future__ import annotations

import json

from llm_loop.cache_guard.guard import PromptGuard
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
    assert m._get_bucket("new-session-1").win_runs == 0  # 新会话窗口从零


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


# ── EVO-20260825: session 分桶隔离（§5.3 并发串台）──


def test_session_buckets_isolated():
    """并发多会话命中统计互不污染——会话 A 低命中不影响会话 B 快照."""
    m = CacheHealthMonitor(min_runs=3, min_tokens=1000)
    # 会话 A: 连续低命中（10%）
    for _ in range(3):
        m.record(20000, 2000, session_id="sess-A")
    # 会话 B: 高命中（97.5%）
    for _ in range(3):
        m.record(20000, 19500, session_id="sess-B")
    snap_a = m.snapshot("sess-A")
    snap_b = m.snapshot("sess-B")
    assert snap_a["win_runs"] == 3 and snap_a["win_in"] == 60000
    assert round(snap_b["win_hit"] / snap_b["win_in"], 3) == 0.975
    # 聚合快照含独立 sessions 分桶
    agg = m.snapshot()
    assert "sess-A"[:12] in agg["sessions"]
    assert "sess-B"[:12] in agg["sessions"]
    assert agg["session_count"] == 2


def test_session_breaker_hit_win_isolated():
    """命中共信号 per-session——会话 A 低命中不影响会话 B 风暴判定."""
    m = CacheHealthMonitor(breaker_trigger_runs=3)
    for _ in range(3):
        m.record(20000, 2000, session_id="storm-sess")  # 10% 低命中
    for _ in range(3):
        m.record(20000, 19500, session_id="healthy-sess")  # 97.5% 高命中
    for _ in range(3):
        m.note_build_result(
            compacted=True,
            anchor_moved=True,
            chars_total=300_000,
            budget=300_000,
            session_id="storm-sess",
        )
    # 仅风暴会话进入 breaker（共信号不跨会话稀释）
    assert m.breaker_active_for("storm-sess") is True
    assert m.breaker_active_for("healthy-sess") is False


def test_fail_alerted_per_session():
    """§5.11: 恢复失败提示 per-session——多会话各自可收到，同会话仅首次."""
    m = CacheHealthMonitor(min_runs=2, min_tokens=1000, recovery_timeout_runs=2)
    # 两个会话分别触发恢复失败
    for sid in ("sess-A", "sess-B"):
        m.note_anchor_moved(session_id=sid)
        for _ in range(2):
            m.record(20000, 2000, session_id=sid)
        assert m.snapshot(sid)["alerted"] is True
        # 拦截期锚点持续移动 → 超时 → 恢复失败提示（每会话首次）
        for _ in range(2):
            m.note_anchor_moved(session_id=sid)
            hint = m.record(20000, 2000, session_id=sid)
        assert "恢复失败" in (hint or "")
    # 两个会话都已提示（进程级单标志旧实现只能提示一次）
    assert m.snapshot("sess-A")["fail_alerted"] is True
    assert m.snapshot("sess-B")["fail_alerted"] is True


def test_note_view_not_shrinking_writes_breaker_audit(tmp_path):
    """任务6.2: head_keep 大裁后视图未缩小（drop<5%）→ 审计事件
    view_not_shrinking_after_compact 落盘（含 pre/post/drop 字段，复发可归因）."""
    audit = tmp_path / "cache_breaker.jsonl"
    m = CacheHealthMonitor(breaker_audit_file=audit)
    m.note_view_not_shrinking(
        pre_chars=288_000,
        post_chars=286_000,
        drop_pct=0.7,
        session_id="s69715765",
        model_ref="minimax/MiniMax-M3",
    )
    lines = audit.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["event"] == "view_not_shrinking_after_compact"
    assert row["session_id"] == "s69715765"
    assert row["model"] == "minimax/MiniMax-M3"
    assert row["pre_chars"] == 288_000
    assert row["post_chars"] == 286_000
    assert row["drop_pct"] == 0.7
    assert "pre=288000" in row["reason"]


# ── 任务10（§5.6）: 多会话并发统计隔离验证 ──


def test_guard_hit_win_isolated_across_sessions():
    """PromptGuard._hit_win 按 session_id 分桶——会话 A 低命中率不污染会话 B 的
    命中率统计与规则 G 判定."""
    g = PromptGuard(hit_telemetry=True)
    # 会话 A: 连续低命中（10%，< _HIT_RATE_BLOCK 0.30）
    for _ in range(3):
        g.record_result("sess-A", tokens_in=20000, tokens_hit=2000)
    # 会话 B: 高命中（97.5%，> _HIT_RATE_WARN 0.85）
    for _ in range(3):
        g.record_result("sess-B", tokens_in=20000, tokens_hit=19500)
    # 各自快照独立（A 的劣化不拖低 B）
    snap_a = g.snapshot("sess-A")
    snap_b = g.snapshot("sess-B")
    assert snap_a["hit_win_size"] == 3
    assert round(snap_a["recent_hit_rate"], 3) == 0.1
    assert snap_b["hit_win_size"] == 3
    assert round(snap_b["recent_hit_rate"], 3) == 0.975
    # 聚合信息
    assert snap_a["sessions_count"] == 2
    # 会话 A 命中率低于 BLOCK 阈值 → 规则 G 触发 BLOCK/WARN；会话 B 不受影响
    low = g._recent_hit_rate("sess-A")
    high = g._recent_hit_rate("sess-B")
    assert low is not None and low < 0.30
    assert high is not None and high > 0.85


def test_guard_and_monitor_snapshot_same_session_key():
    """PromptGuard.snapshot(sid) 与 CacheHealthMonitor.snapshot(sid) 使用相同
    session_id key——调用方以同一 sid 可同时取到两者会话级状态（无 key 漂移）."""
    sid = "sess-同-key-01"
    g = PromptGuard(hit_telemetry=True)
    m = CacheHealthMonitor(min_runs=3, min_tokens=1000)
    for _ in range(3):
        g.record_result(sid, tokens_in=20000, tokens_hit=19500)
        m.record(20000, 19500, session_id=sid)
    g_snap = g.snapshot(sid)
    m_snap = m.snapshot(sid)
    # guard: 命中率 97.5%
    assert round(g_snap["recent_hit_rate"], 3) == 0.975
    # monitor: 同 sid 窗口命中率 97.5%
    assert round(m_snap["win_hit"] / m_snap["win_in"], 3) == 0.975
    assert m_snap["win_runs"] == 3
    # 聚合快照中以同 key 前缀可找到该会话
    agg_m = m.snapshot()
    assert sid[:12] in agg_m["sessions"]


def test_breaker_audit_rows_carry_session_id(tmp_path):
    """breaker 审计 JSONL 每条含 session_id——多会话并发时事件可按会话归因."""
    audit = tmp_path / "cache_breaker.jsonl"
    m = CacheHealthMonitor(breaker_trigger_runs=3, breaker_audit_file=audit)
    for _ in range(3):
        m.record(20000, 2000, session_id="sess-break-A")
    for _ in range(3):
        m.note_build_result(
            compacted=True,
            anchor_moved=True,
            chars_total=300_000,
            budget=300_000,
            session_id="sess-break-A",
        )
    assert m.breaker_active_for("sess-break-A") is True
    lines = audit.read_text(encoding="utf-8").strip().splitlines()
    assert lines, "breaker 审计应有记录"
    rows = [json.loads(line) for line in lines]
    # 存在进入熔断事件且带 session_id（可归因到具体会话）
    enter_rows = [r for r in rows if r.get("event") == "breaker_enter"]
    assert enter_rows, "应有 breaker_enter 审计事件"
    assert all(r.get("session_id") == "sess-break-A" for r in enter_rows)
