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
    """破坏型（锚点前移）低命中 → 告警 + 拦截（强制缓存友好压缩）."""
    m = CacheHealthMonitor()
    m.note_anchor_moved()  # 窗口内有锚点前移 → 破坏型归因
    hint = None
    for _ in range(5):
        hint = m.record(20000, 2000)  # 10% hit
    snap = m.snapshot()
    assert snap["alerted"] is True
    assert m.force_head_keep is True
    assert hint and "[缓存命中告警]" in hint and "拦截" in hint


def test_alert_message_shows_real_window_numbers():
    """EVO-20260817-5b991577 缺陷1: 告警文案用 reset 前快照，不显示 0/0."""
    m = CacheHealthMonitor()
    m.note_anchor_moved()
    hint = None
    for _ in range(5):
        hint = m.record(20000, 2000)  # 5×20000=100K in, 5×2000=10K hit → 10%
    assert hint is not None
    assert "近 5 次 run" in hint and "10%" in hint
    assert "（10000/100000 tokens）" in hint  # 真实数值(hit/in)，非 0/0
    assert "0/0" not in hint


def test_design_low_hit_observes_only():
    """设计型（锚点未前移）低命中 → 只观察不告警不拦截（小窗口设计值）."""
    m = CacheHealthMonitor()
    hint = None
    for _ in range(5):
        hint = m.record(20000, 2000)  # 10% hit，无锚点前移
    snap = m.snapshot()
    assert snap["alerted"] is False
    assert m.force_head_keep is False
    assert hint is None
    assert snap["win_hit"] > 0  # 观察仍在累计（快照可查）


def test_anchor_move_cause_attribution():
    """归因: 窗口内有锚点前移 → 告警文案标注压缩破坏前缀."""
    m = CacheHealthMonitor()
    for _ in range(3):
        m.note_anchor_moved()
    hint = None
    for _ in range(5):
        hint = m.record(20000, 2000)
    assert hint and "压缩锚点前移破坏前缀" in hint


def test_recover_when_anchor_stops_moving():
    """恢复: 拦截后锚点不再前移连续 5 轮 → 解除（不再依赖命中率回升）."""
    m = CacheHealthMonitor()
    m.note_anchor_moved()
    for _ in range(5):
        m.record(20000, 2000)
    assert m.force_head_keep is True
    snap = m.snapshot()
    assert snap["win_runs"] == 0  # 告警已复位窗口
    # 拦截期锚点继续前移 → 保持拦截
    for _ in range(4):
        m.note_anchor_moved()
        m.record(20000, 2000)
    assert m.force_head_keep is True
    # 锚点停止前移连续 5 轮（命中率仍低，设计值）→ 解除
    hint = None
    for _ in range(5):
        hint = m.record(20000, 2000)
    snap = m.snapshot()
    assert snap["alerted"] is False
    assert m.force_head_keep is False
    assert snap["anchor_move_runs"] == 0
    assert hint and "[缓存已恢复]" in hint


def test_can_alert_again_after_recovery():
    """闭环: 恢复后再破坏（锚点前移）→ 可再次告警（不再每进程仅一次）."""
    m = CacheHealthMonitor()
    m.note_anchor_moved()
    for _ in range(5):
        m.record(20000, 2000)
    assert m.force_head_keep is True
    for _ in range(5):
        m.record(20000, 2000)  # 锚点停止前移 → 恢复
    assert m.force_head_keep is False
    hint = None
    for _ in range(5):
        m.note_anchor_moved()
        hint = m.record(20000, 2000)
    assert hint and "[缓存命中告警]" in hint


def test_recovery_timeout_failure_hint_once():
    """超时兜底: 拦截期累计 recovery_timeout_runs 轮未恢复 → 恢复失败短消息 + 解除（每进程一次）."""
    m = CacheHealthMonitor(recovery_timeout_runs=5)
    m.note_anchor_moved()
    for _ in range(5):
        m.record(20000, 2000)
    assert m.force_head_keep is True
    hint = None
    for _ in range(5):
        m.note_anchor_moved()  # 拦截期锚点持续前移 → 不恢复，直至超时
        hint = m.record(20000, 2000)
    assert hint and "[缓存恢复失败]" in hint
    snap = m.snapshot()
    assert snap["alerted"] is False and m.force_head_keep is False
    assert snap["fail_alerted"] is True


def test_recovery_fail_suppresses_repeat_alert():
    """恢复失败后抑制重复告警: 同进程不再重复告警/提示（防刷屏）."""
    m = CacheHealthMonitor(recovery_timeout_runs=5)
    m.note_anchor_moved()
    for _ in range(5):
        m.record(20000, 2000)
    for _ in range(5):
        m.note_anchor_moved()
        m.record(20000, 2000)  # 触发恢复失败
    # 之后再次恶化（锚点前移+低命中）→ 不再告警（fail_alerted 抑制）
    hint = None
    for _ in range(6):
        m.note_anchor_moved()
        hint = m.record(20000, 2000)
    assert hint is None
    assert m.force_head_keep is False
    assert m.snapshot()["alerted"] is False


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
    m.note_anchor_moved()  # 破坏型归因（否则设计型不告警不置标记）
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
