"""EVO-20260810-86e777d1: 演进待审阅弹窗提醒测试."""
from unittest import mock

from llm_loop.introspection.events import ArchitectureEventType
from llm_loop.introspection.loop_signals import LoopSignalDetector
from llm_loop.notify import notify


class _FakeStore:
    def __init__(self, status_items):
        self._items = status_items

    def list(self, status=""):
        if status:
            return [i for i in self._items if i.get("status") == status]
        return self._items


def test_pending_review_detects_and_notifies():
    """有 pending_review → 授权弹窗被调用 + 返回 DEVIATION 事件."""
    store = _FakeStore([{"id": "EVO-TEST-1", "status": "pending_review"}])
    det = LoopSignalDetector(popup_pending_review=True)
    with mock.patch("llm_loop.introspection.loop_signals.confirm", return_value=False) as m:
        event = det.check_pending_review(store)
    assert event is not None
    assert event.event_type == ArchitectureEventType.DEVIATION
    assert "EVO-TEST-1" in event.fact
    m.assert_called_once()  # 授权弹窗被触发


def test_no_pending_review_returns_none():
    """无 pending_review → None（不弹窗不注入）."""
    store = _FakeStore([{"id": "EVO-TEST-2", "status": "executed"}])
    det = LoopSignalDetector()
    with mock.patch("llm_loop.introspection.loop_signals.confirm") as m:
        event = det.check_pending_review(store)
    assert event is None
    m.assert_not_called()


def test_store_none_fail_open():
    """store 为 None → None（fail-open，不阻断）."""
    det = LoopSignalDetector()
    assert det.check_pending_review(None) is None


def test_notify_failure_fallback_event():
    """confirm 弹窗异常 → 降级拒绝 + 仍返回事件（不真实弹窗、不阻断）.

    修复（EVO-20260811）: 原 Mock 的是 notify（check_pending_review 实际调用 confirm），
    Mock 错函数导致测试运行时真实弹出 osascript 授权窗（EVO-TEST-3）。
    """
    store = _FakeStore([{"id": "EVO-TEST-3", "status": "pending_review"}])
    det = LoopSignalDetector(popup_pending_review=True)
    with mock.patch("llm_loop.introspection.loop_signals.confirm", side_effect=RuntimeError("boom")):
        event = det.check_pending_review(store)
    assert event is not None
    assert "EVO-TEST-3" in event.fact


def test_notify_real_osascript_available(monkeypatch):
    """notify 封装: 返回 bool（模拟 osascript 不可用 → False，不真实发通知打扰）.

    修复（EVO-20260811 测试副作用审计）: 原真实调用 notify 会发系统通知（打扰），
    改为模拟 osascript 不可用（which 返回 None）→ 降级 False，验证健壮性。
    """
    import shutil

    monkeypatch.setattr(shutil, "which", lambda *a, **k: None)  # osascript 不可用
    result = notify("", "")
    assert result is False
