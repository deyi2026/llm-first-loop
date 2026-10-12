# EVO-20260827-ad73251b: 命中趋势转折点观测单测
from llm_loop.core.cache_health import CacheHealthMonitor


def test_coldstart_trendmarks_first_recovery_and_streak():
    m = CacheHealthMonitor()
    for _ in range(3):
        m.record(10_000, 0, session_id="s1")  # 冷启动 hit=0
    for _ in range(5):
        m.record(11_000, 9_000, session_id="s1")  # 第4轮起恢复
    snap = m.snapshot()["sessions"]["s1"]
    tr = snap["trend"]
    assert tr["first_recovery_round"] == 4
    assert tr["current_streak"] == 5
    assert tr["samples"] == 8 and tr["total_rounds"] == 8


def test_destructive_low_streak_with_anchor_move():
    m = CacheHealthMonitor()
    m.note_anchor_moved("s1")
    for _ in range(6):
        m.record(20_000, 0, session_id="s1")  # 持续全 miss（破坏型窗口内零命中）
    tr = m.snapshot()["sessions"]["s1"]["trend"]
    assert tr["first_recovery_round"] is None
    assert tr["current_streak"] == 0


def test_ring_buffer_caps_at_30():
    m = CacheHealthMonitor()
    for i in range(40):
        m.record(100, 50 + i, session_id="s2")
    tr = m.snapshot()["sessions"]["s2"]["trend"]
    assert tr["samples"] == 30 and tr["total_rounds"] == 40
    # first_recovery 取窗口内首个 hit>0——环形淘汰后为第 11 轮
    assert tr["first_recovery_round"] == 11
    assert len(tr["recent"]) == 10


def test_model_switch_resets_trend():
    m = CacheHealthMonitor()
    m.record(10_000, 0, model_ref="a", session_id="s3")
    m.record(10_000, 9_000, model_ref="b", session_id="s3")  # 切换→新桶
    m.record(10_000, 9_000, model_ref="b", session_id="s3")
    tr = m.snapshot()["sessions"]["s3"]["trend"]
    assert tr["total_rounds"] == 2  # 切换前旧桶样本不残留
    assert tr["first_recovery_round"] == 1
