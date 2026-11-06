# R-04（M1 修订批次，外部审查 2026-11-06 复核 §4）：有界缓存不得淘汰先入队的
# 关键事件；关键历史覆盖丢失要如实单独计数；diag 接入实际回执。
"""红→绿契约（红由 git stash src 改动验证）：基线 5e295e1e0 上三条全红。

- 基线缺陷：界满时新关键事件 pop(0) 弹队首——先入队的 dialog-opening
  会被普通事件流淹没后的新关键事件挤掉（审查 §3.2 探针复现）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from test_browser_cdp_dialog_recovery_v02 import _actuator, _DialogBlockedWs

from llm_loop.browser.cdp_action_host import (
    _BOUNDARY_CRITICAL_EVENT_METHODS,
    _MAX_BUFFERED_EVENTS,
    _MutationCdpSession,
)


def _event(method: str, seq: int) -> dict:
    return {"method": method, "params": {"timestamp": seq}}


class _NullWs:
    def send(self, payload: str) -> None:  # noqa: ARG002
        return None

    def recv(self, timeout: float | None = None):  # noqa: ARG002
        raise AssertionError("不应走到 recv")

    def close(self) -> None:
        return None


def test_r04_critical_first_in_queue_survives_normal_flood() -> None:
    assert "Page.javascriptDialogOpening" in _BOUNDARY_CRITICAL_EVENT_METHODS
    session = _MutationCdpSession(_NullWs())
    session._buffer_event(_event("Page.javascriptDialogOpening", 0))
    for i in range(_MAX_BUFFERED_EVENTS - 1):  # 普通事件填满其余位置
        session._buffer_event(_event("Runtime.consoleAPICalled", i))
    assert len(session._events) == _MAX_BUFFERED_EVENTS
    # 新关键事件（window-open）到来：淘汰的必须是最旧普通事件，dialog-opening 保留
    session._buffer_event(_event("Page.windowOpen", 999))
    methods = [m.get("method") for m in session._events]
    assert "Page.javascriptDialogOpening" in methods, "先入队的关键事件被普通事件流挤掉"
    assert methods.count("Page.windowOpen") == 1
    assert len(methods) == _MAX_BUFFERED_EVENTS  # 容量不变
    assert session.events_dropped == 1  # 让位的普通事件如实计数
    assert session.critical_events_evicted == 0


def test_r04_all_critical_overflow_counted_separately() -> None:
    session = _MutationCdpSession(_NullWs())
    for i in range(_MAX_BUFFERED_EVENTS):
        session._buffer_event(_event("Page.javascriptDialogOpening", i))
    session._buffer_event(_event("Page.windowOpen", _MAX_BUFFERED_EVENTS))
    methods = [m.get("method") for m in session._events]
    assert len(methods) == _MAX_BUFFERED_EVENTS
    # 全关键超限：最旧关键让位，单独计数——不与普通丢弃混同
    assert session.critical_events_evicted == 1
    assert session.events_dropped == 0
    diag = session.diag()
    assert diag["critical_events_evicted"] == 1
    assert diag["events_dropped"] == 0


def test_r04_diag_reaches_timeout_receipt() -> None:
    ws = _DialogBlockedWs()
    actuator, _counter = _actuator(ws)
    import pytest

    # fill 的 callFunctionOn 应答被弹窗阻塞 → TimeoutError 直达 dispatch 层
    # timeout 分支（press_key 会被 _PressKeyPartialDispatchError 提前包装）。
    with pytest.raises(RuntimeError, match="timed out") as excinfo:
        actuator.dispatch(
            verb="fill", physical_target="dom:1", args={"text": "x", "mode": "replace"}
        )
    msg = str(excinfo.value)
    # R-04：诊断不再只是内部方法——超时回执携带 diag 摘要，模型可判别
    # "弹窗阻塞"（events_buffered 中有边界事件）vs "页面死重"。
    assert "diag=" in msg
    assert "events_dropped" in msg
    assert "late_responses" in msg
