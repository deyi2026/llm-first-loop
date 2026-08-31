"""取消双路径单元测试（T2，tasks 1.6）：registry 命中 / _sync_active 命中 / 双未命中."""

from __future__ import annotations

import threading

from llm_loop.core.loop.runner import (
    CANCEL_REASON_RUNNER_STOP,
    CANCEL_REASON_USER_STOP,
    BackgroundRunner,
    RunHandle,
)
from llm_loop.llm.client import LLMResponse


class _FakeEngine:
    def __init__(self) -> None:
        self._sync_active: set[str] = set()
        self._sync_guard = threading.Lock()
        self.registry = None


def test_cancel_registry_hit_writes_reason():
    runner = BackgroundRunner(_FakeEngine())
    runner._registry["s1"] = RunHandle(session_id="s1")
    assert runner.cancel("s1", CANCEL_REASON_USER_STOP) is True
    h = runner._registry["s1"]
    assert h.cancelled is True
    assert h.cancel_reason == "user_stop"
    assert runner.is_cancelled("s1") is True
    assert runner.cancel_reason("s1") == "user_stop"


def test_cancel_sync_active_falls_back_to_sync_registry():
    engine = _FakeEngine()
    runner = BackgroundRunner(engine)
    engine._sync_active.add("s2")
    assert runner.cancel("s2", CANCEL_REASON_USER_STOP) is True
    assert runner._sync_cancelled == {"s2": "user_stop"}
    assert runner.is_cancelled("s2") is True
    assert runner.cancel_reason("s2") == "user_stop"


def test_cancel_no_active_run_returns_false():
    runner = BackgroundRunner(_FakeEngine())
    assert runner.cancel("s3") is False
    assert runner.is_cancelled("s3") is False
    assert runner.cancel_reason("s3") == ""


def test_reasons_distinguishable_user_vs_runner():
    engine = _FakeEngine()
    runner = BackgroundRunner(engine)
    runner._registry["bg"] = RunHandle(session_id="bg")
    engine._sync_active.add("sync")
    runner.cancel("bg", CANCEL_REASON_RUNNER_STOP)
    runner.cancel("sync", CANCEL_REASON_USER_STOP)
    assert runner.cancel_reason("bg") == "runner_stop"
    assert runner.cancel_reason("sync") == "user_stop"


def test_cancel_default_reason_is_user_stop():
    runner = BackgroundRunner(_FakeEngine())
    runner._registry["s"] = RunHandle(session_id="s")
    runner.cancel("s")
    assert runner._registry["s"].cancel_reason == "user_stop"


def test_discard_sync_cancel_clears_marker():
    engine = _FakeEngine()
    runner = BackgroundRunner(engine)
    engine._sync_active.add("s")
    runner.cancel("s")
    runner.discard_sync_cancel("s")
    assert runner.is_cancelled("s") is False
    assert runner.cancel_reason("s") == ""


def test_stale_marker_cleared_on_new_run_registration(build_test_engine):
    engine, _fake = build_test_engine([{"content": "ok"}])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()
    runner._sync_cancelled[sid] = "user_stop"
    result = engine.run(sid, "hello")
    assert result.cancel_reason == ""
    assert result.final_answer == "ok"
    assert runner.is_cancelled(sid) is False


def test_marker_cleared_when_run_unregisters(build_test_engine):
    engine, _fake = build_test_engine([{"content": "ok"}])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()
    engine._sync_active.add(sid)
    runner.cancel(sid)
    assert runner.is_cancelled(sid) is True
    engine._sync_active.discard(sid)
    engine._sync_cancel_discard(sid)
    assert runner.is_cancelled(sid) is False


def test_sync_admission_clears_stale_before_active_publish(build_test_engine, monkeypatch):
    """回归 lost-stop：初始化清 stale 时 run 尚未发布 active；发布后 accepted stop 不再被清。"""
    engine, fake = build_test_engine([])
    runner = BackgroundRunner(engine)
    engine.runner = runner
    sid = engine.session.create()
    runner._sync_cancelled[sid] = "user_stop"  # 模拟上一轮异常残留

    original_discard = runner.discard_sync_cancel
    observed: list[tuple[bool, bool]] = []

    def _observe_discard(session_id: str) -> None:
        # lifecycle 必须先清 stale 再发布 _sync_active；否则这里 cancel 会被错误受理，
        # 随后的 discard 又把刚受理的 stop 清掉。
        observed.append((runner.is_sync_active(session_id), runner.cancel(session_id)))
        original_discard(session_id)

    monkeypatch.setattr(runner, "discard_sync_cancel", _observe_discard)

    def _cancel_after_publish(calls):
        assert runner.is_sync_active(sid) is True
        assert runner.cancel(sid) is True
        assert runner.cancel_reason(sid) == "user_stop"
        return LLMResponse(content="本不应作为正常完成结果", tool_calls=[], provider="fake")

    fake._responses = [_cancel_after_publish]
    result = engine.run(sid, "hello")

    assert observed and observed[0] == (False, False)
    assert all(item == (False, False) for item in observed)
    assert result.cancel_reason == "user_stop"
    assert result.final_answer.startswith("（已停止")
    assert runner.is_cancelled(sid) is False  # finally 生命周期清理
