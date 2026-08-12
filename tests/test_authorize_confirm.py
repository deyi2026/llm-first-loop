"""授权确认弹窗测试（EVO-20260810-86e777d1 演进: 通知型→授权确认型）."""
from unittest import mock

from llm_loop.introspection.loop_signals import LoopSignalDetector
from llm_loop.notify import confirm, notify


class _FakeStore:
    def __init__(self, items):
        self._items = items
        self.reviewed = []

    def list(self, status=""):
        if status:
            return [i for i in self._items if i.get("status") == status]
        return self._items

    def review(self, sid, decision):
        self.reviewed.append((sid, decision))
        for i in self._items:
            if i.get("id") == sid:
                i["status"] = "accepted"
        return {"id": sid, "status": "accepted"}


def test_confirm_granted_auto_reviews():
    """用户点确认 → store.review(accepted) 自动执行，无需复制命令."""
    store = _FakeStore([{"id": "EVO-C1", "status": "pending_review", "content": "测试建议"}])
    det = LoopSignalDetector()
    with mock.patch("llm_loop.introspection.loop_signals.confirm", return_value=True):
        event = det.check_pending_review(store)
    assert store.reviewed == [("EVO-C1", "accepted")]  # 自动审阅
    assert event is not None
    assert "EVO-C1" in event.fact and "accepted" in event.fact


def test_confirm_rejected_fallback():
    """用户点拒绝 → 不自动审阅，降级文本引导."""
    store = _FakeStore([{"id": "EVO-C2", "status": "pending_review", "content": "测试"}])
    det = LoopSignalDetector()
    with mock.patch("llm_loop.introspection.loop_signals.confirm", return_value=False):
        event = det.check_pending_review(store)
    assert store.reviewed == []  # 未审阅
    assert event is not None and "待审阅" in event.fact


def test_no_pending_returns_none():
    store = _FakeStore([{"id": "EVO-C3", "status": "executed"}])
    det = LoopSignalDetector()
    with mock.patch("llm_loop.introspection.loop_signals.confirm") as m:
        event = det.check_pending_review(store)
    assert event is None
    m.assert_not_called()


def test_confirm_failure_fallback():
    """confirm 异常 → 降级拒绝（不阻断）."""
    store = _FakeStore([{"id": "EVO-C4", "status": "pending_review", "content": "x"}])
    det = LoopSignalDetector()
    with mock.patch("llm_loop.introspection.loop_signals.confirm", side_effect=RuntimeError("boom")):
        event = det.check_pending_review(store)
    assert store.reviewed == []
    assert event is not None


def test_confirm_real_returns_bool(monkeypatch):
    """confirm 封装: 返回 bool（osascript 不可用时 False，不真实弹窗打扰）.

    修复（EVO-20260811）: 原真实调用 confirm 会弹出 osascript 授权窗（测试打扰），
    改为模拟 osascript 不可用（which 返回 None）→ 走降级 False 分支，验证健壮性。
    """
    import shutil

    monkeypatch.setattr(shutil, "which", lambda *a, **k: None)  # osascript 不可用
    assert confirm("t", "m") is False
    assert notify("t", "m") is False


def test_same_pending_only_prompts_once():
    """同建议保持 pending：第一次弹窗，第二次不再弹（去重）."""
    store = _FakeStore([{"id": "EVO-D1", "status": "pending_review", "content": "x"}])
    det = LoopSignalDetector()
    with mock.patch("llm_loop.introspection.loop_signals.confirm", return_value=False) as m:
        ev1 = det.check_pending_review(store)   # 第一次: 弹窗（拒绝）
        ev2 = det.check_pending_review(store)   # 第二次: 不应再弹
    assert m.call_count == 1  # 只弹一次
    assert ev1 is not None
    assert ev2 is None  # 去重生效


def test_different_pending_each_prompts():
    """不同建议各自弹窗（不误伤）."""
    det = LoopSignalDetector()
    with mock.patch("llm_loop.introspection.loop_signals.confirm", return_value=False):
        s1 = _FakeStore([{"id": "EVO-E1", "status": "pending_review", "content": "a"}])
        assert det.check_pending_review(s1) is not None
        s2 = _FakeStore([{"id": "EVO-E2", "status": "pending_review", "content": "b"}])
        assert det.check_pending_review(s2) is not None


def test_confirmed_then_no_repeat():
    """确认审阅后建议变 accepted → 自然不再 pending，也不再弹."""
    store = _FakeStore([{"id": "EVO-F1", "status": "pending_review", "content": "x"}])
    det = LoopSignalDetector()
    with mock.patch("llm_loop.introspection.loop_signals.confirm", return_value=True):
        det.check_pending_review(store)
    assert store.reviewed == [("EVO-F1", "accepted")]
    # 状态已变 accepted → list(pending) 为空 → 无弹窗
    with mock.patch("llm_loop.introspection.loop_signals.confirm") as m:
        assert det.check_pending_review(store) is None
    m.assert_not_called()
