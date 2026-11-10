# B-02 CDP 请求总 deadline 与有界事件缓存（M1 TASK-15377274-005，DESIGN v1.1 §3.5/§5.6，T-09）
"""红→绿契约：基线 7ae768519 上逐条失败；修复后全绿。

- 接收循环必须是 monotonic 总 deadline：事件到达不延长预算
  （基线红：每个事件重置 recv 超时，总时长可超预算数倍）。
- 事件缓存有界（条数上限）且暴露丢弃计数；弹窗关键事件
  （Page.javascriptDialogOpening/downloadWillBegin/windowOpen）永不因界被丢。
- 迟到旧 id 响应显式失效计数（不静默、不串号；§5.6）。
"""

from __future__ import annotations

import json
import time
from typing import Any


class _ScriptedWs:
    """按脚本回放的假 websocket：条目 ('event', obj) / ('late', id) / ('sleep_event', obj, s) / ('result', id)。

    - event：立即返回一条无 id 事件消息。
    - sleep_event：阻塞 s 秒后返回事件（模拟慢速事件流）。
    - late：返回一条旧 id 的响应（无 method）。
    - result：返回该 id 的正常响应并结束。
    """

    def __init__(self, script: list[tuple[str, Any]] | list[tuple[str, Any, float]]):
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []
        self._exhausted = False

    def send(self, payload: str) -> None:
        self.requests.append(json.loads(payload))

    def recv(self, timeout: float | None = None) -> str:
        if not self.script:
            self._exhausted = True
            raise TimeoutError("no more scripted messages")
        head = self.script.pop(0)
        kind = head[0]
        if kind == "event":
            return json.dumps({"method": head[1], "params": {}})
        if kind == "sleep_event":
            delay = float(head[2])
            if timeout is not None and delay > max(0.0, timeout):
                time.sleep(max(0.0, timeout))
                raise TimeoutError("scripted recv timed out")
            time.sleep(delay)
            return json.dumps({"method": head[1], "params": {}})
        if kind == "late":
            return json.dumps({"id": head[1], "result": {"stale": True}})
        if kind == "result":
            return json.dumps({"id": head[1], "result": {"ok": True}})
        raise AssertionError(f"unknown script kind: {kind}")

    def close(self) -> None:
        return None


def _flood_events(n: int) -> list[tuple[str, str]]:
    return [("event", "Page.frameStartedLoading") for _ in range(n)]


# ── monotonic deadline：事件到达不延长预算 ───────────────────────────

def test_t09_mutation_session_total_deadline_not_reset_by_events():
    """基线（红）：慢速事件流每个都重置 1.0s 预算 → 总耗时 2.1s+；
    修复后：预算按剩余时长递减，总耗时 ≤1.5s。"""
    import pytest

    from llm_loop.browser.cdp_action_host import _MutationCdpSession

    ws = _ScriptedWs(
        [
            ("sleep_event", "Page.frameStartedLoading", 0.7),
            ("sleep_event", "Page.frameStartedLoading", 0.7),
            ("sleep_event", "Page.frameStartedLoading", 0.7),
            ("result", 1),
        ]
    )
    session = _MutationCdpSession(ws, timeout_s=1.0)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        session.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "a"})
    elapsed = time.monotonic() - started
    assert elapsed < 1.5, f"事件到达不得延长预算：elapsed={elapsed:.2f}s > 1.0s 总预算"


def test_t09_readonly_session_total_deadline_not_reset_by_events():
    import pytest

    from llm_loop.browser.cdp_host import _ReadOnlyCdpSession

    ws = _ScriptedWs(
        [
            ("sleep_event", "Page.frameStartedLoading", 0.35),
            ("sleep_event", "Page.frameStartedLoading", 0.35),
            ("sleep_event", "Page.frameStartedLoading", 0.35),
        ]
    )
    session = _ReadOnlyCdpSession(ws, timeout_s=0.5)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        session._request("DOMSnapshot.captureSnapshot", {})
    elapsed = time.monotonic() - started
    assert elapsed < 0.75, f"事件到达不得延长预算：elapsed={elapsed:.2f}s > 0.5s 总预算"


# ── 事件缓存有界 + 弹窗关键状态不丢 + 丢弃计数 ──────────────────────

def test_t09_mutation_session_event_buffer_is_bounded_with_drop_counter():
    from llm_loop.browser.cdp_action_host import _MAX_BUFFERED_EVENTS, _MutationCdpSession

    ws = _ScriptedWs(_flood_events(_MAX_BUFFERED_EVENTS + 300) + [("result", 1)])
    session = _MutationCdpSession(ws, timeout_s=5.0)
    session.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "a"})
    events = session.pop_events()
    assert len(events) <= _MAX_BUFFERED_EVENTS
    assert session.events_dropped >= 300, "丢弃必须计数，不得静默丢失"


def test_t09_mutation_session_dialog_events_never_dropped_by_bound():
    from llm_loop.browser.cdp_action_host import _MAX_BUFFERED_EVENTS, _MutationCdpSession

    script: list[tuple[str, Any]] = []
    for i in range(_MAX_BUFFERED_EVENTS + 100):
        script.append(("event", "Page.frameStartedLoading"))
        if i % 50 == 25:
            script.append(("event", "Page.javascriptDialogOpening"))
    script.append(("result", 1))
    ws = _ScriptedWs(script)
    session = _MutationCdpSession(ws, timeout_s=5.0)
    session.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "a"})
    events = session.pop_events()
    dialogs = [e for e in events if e.get("method") == "Page.javascriptDialogOpening"]
    assert len(dialogs) >= 4, "弹窗关键事件不得因缓存界被丢弃"
    assert len(events) <= _MAX_BUFFERED_EVENTS


# ── 迟到旧 id 响应：显式失效计数（§5.6）────────────────────────────

def test_t09_mutation_session_late_stale_response_counted_not_silent():
    from llm_loop.browser.cdp_action_host import _MutationCdpSession

    ws = _ScriptedWs([("late", 99), ("late", 42), ("result", 1)])
    session = _MutationCdpSession(ws, timeout_s=5.0)
    result = session.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "a"})
    assert result == {"ok": True}
    assert session.late_responses == 2, "迟到旧 id 响应必须显式计数（不静默、不串号）"
    # 迟到响应不得被当作事件缓存（无 method，也不得混入 boundary 通道）
    assert session.pop_events() == []
