"""EVO-20260817-72fcd94a: 缓存健康闭环单测（检测→告警→拦截→恢复 + 发送前门禁）.

覆盖: 正常窗口不告警 / 低命中触发告警+拦截 / 归因锚点前移 / 恢复后解除拦截并复位 /
可再次告警 / 门禁 preflight 漂移→强制缓存友好 / postcheck 合规出闸与漂移提示。
"""

from __future__ import annotations

from llm_loop.core.cache_health import CacheHealthMonitor


def _mon(**kw) -> CacheHealthMonitor:
    m = CacheHealthMonitor()
    for k, v in kw.items():
        setattr(m, f"_{k}", v)
    return m


def test_ok_window_no_alert():
    """窗口达标但命中率高 → 不告警、不拦截."""
    m = CacheHealthMonitor()
    for _ in range(6):
        hint = m.record(20000, 19500)  # 97.5% hit
    assert hint is None
    snap = m.snapshot()
    assert snap["alerted"] is False and snap["force_head_keep"] is False


def test_low_hit_rate_alerts_and_intercepts():
    """低命中 → 告警 + 拦截（强制缓存友好压缩）."""
    m = CacheHealthMonitor()
    hint = None
    for _ in range(5):
        hint = m.record(20000, 2000)  # 10% hit
    snap = m.snapshot()
    assert snap["alerted"] is True
    assert m.force_head_keep is True
    assert hint and "[缓存命中告警]" in hint and "拦截" in hint


def test_anchor_move_cause_attribution():
    """归因: 窗口内有锚点前移 → 告警文案标注压缩破坏前缀."""
    m = CacheHealthMonitor()
    for _ in range(3):
        m.note_anchor_moved()
    hint = None
    for _ in range(5):
        hint = m.record(20000, 2000)
    assert hint and "压缩锚点前移破坏前缀" in hint


def test_recover_after_hit_rate_returns():
    """恢复: 告警（复位窗口）→ 拦截期低命中 → 连续 5 轮单轮 ≥80% → 恢复."""
    m = CacheHealthMonitor()
    for _ in range(5):
        m.record(20000, 2000)
    assert m.force_head_keep is True
    snap = m.snapshot()
    assert snap["win_runs"] == 0  # 告警已复位窗口
    for _ in range(4):
        m.record(20000, 2000)
    assert m.force_head_keep is True  # 拦截期低命中 → 保持
    hint = None
    for _ in range(5):
        hint = m.record(20000, 19500)  # 97.5% 单轮命中
    snap = m.snapshot()
    assert snap["alerted"] is False
    assert m.force_head_keep is False
    assert snap["win_runs"] == 0 and snap["anchor_move_runs"] == 0
    assert hint and "[缓存已恢复]" in hint


def test_can_alert_again_after_recovery():
    """闭环: 恢复后再次恶化 → 可再次告警（不再每进程仅一次）."""
    m = CacheHealthMonitor()
    for _ in range(5):
        m.record(20000, 2000)
    assert m.force_head_keep is True
    for _ in range(5):
        m.record(20000, 19500)
    assert m.force_head_keep is False
    hint = None
    for _ in range(5):
        hint = m.record(20000, 2000)
    assert hint and "[缓存命中告警]" in hint


def test_gate_preflight_drift_forces_head_keep():
    """门禁预检: 稳定段指纹与该 session 基线不符 → 强制缓存友好压缩（当次合规化）."""
    m = CacheHealthMonitor()
    # 首次发送建立基线
    m.postcheck("s1", "fp-A")
    assert m.force_head_keep is False
    # 稳定段漂移 → preflight 触发拦截
    m.preflight("s1", "fp-B")
    assert m.force_head_keep is True
    assert m.snapshot()["gate_drift_count"] == 1
    # 稳定段恢复一致 → 不再触发
    m.preflight("s1", "fp-A")
    assert m.snapshot()["gate_drift_count"] == 1


def test_gate_postcheck_compliance_and_drift():
    """门禁后检: 合规 → 出闸；不合规 → 漂移提示（fail-open 不阻断）；受控变化建新基线."""
    m = CacheHealthMonitor()
    assert m.postcheck("s1", "fp-A") is None  # 首次建基线
    assert m.postcheck("s1", "fp-A") is None  # 合规
    hint = m.postcheck("s1", "fp-B")  # 漂移
    assert hint and "拼装合规提示" in hint
    # 漂移后已建新基线 → 后续一致不再提示
    assert m.postcheck("s1", "fp-B") is None


def test_gate_per_session_baseline():
    """门禁: 基线 per-session——不同会话注入/记忆不同，互不误报."""
    m = CacheHealthMonitor()
    m.postcheck("s1", "fp-A")
    m.postcheck("s2", "fp-X")
    # s1 稳定不变 → 不提示；s2 也是自己的基线
    assert m.postcheck("s1", "fp-A") is None
    assert m.postcheck("s2", "fp-X") is None
    # s1 漂移只影响 s1
    hint = m.postcheck("s1", "fp-B")
    assert hint is not None
    assert m.postcheck("s2", "fp-X") is None


def test_gate_first_send_builds_baseline():
    """门禁: 首次发送（无基线）只建基线，不告警."""
    m = CacheHealthMonitor()
    hint = m.postcheck("s1", "fp-first")
    assert hint is None
    assert m.postcheck("s1", "fp-first") is None
    assert m.snapshot()["baselines"].get("s1") == "fp-first"  # 基线按 session 建立


def test_gate_note_injected_once_on_activation():
    """知情标记: 干预激活首轮待注入（take 一次），消费后不再重复."""
    m = CacheHealthMonitor()
    # 激活（低命中告警）
    for _ in range(5):
        m.record(20000, 2000)
    snap = m.snapshot()
    assert snap["gate_note_pending"] is True
    # 一次性消费
    assert m.take_gate_note() is True
    assert m.take_gate_note() is False  # 已消费
    # 漂移激活也会置 pending
    m.postcheck("s1", "fp-A")
    m.preflight("s1", "fp-B")
    assert m.snapshot()["gate_note_pending"] is True
    assert m.take_gate_note() is True


def test_gate_note_not_pending_when_healthy():
    """知情标记: 正常窗口（无干预）不置 pending."""
    m = CacheHealthMonitor()
    for _ in range(6):
        m.record(20000, 19500)
    assert m.snapshot()["gate_note_pending"] is False
    assert m.take_gate_note() is False
