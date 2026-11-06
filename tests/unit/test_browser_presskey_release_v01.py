# B-04 组合键失败释放补偿（M1 TASK-15377274-006，DESIGN v1.1 §3.7/§8 T-11）
"""红→绿契约：基线 7ae768519 上逐条失败；修复后全绿。

- 组合键序列维护已按下集合；任一投递异常时在同一原始目标连接上逆序
  尽力 keyUp 释放，回执携带 cleanup 状态（released/partial/input_state_unknown）。
- 连接已失效时显式 input_state_unknown + 重观测路径；不得继续投递。
- 只清理输入状态：不重演业务快捷键、不切换标签补发。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_browser_m2a_presskey_hover_dialog_download_v01 import _attest_dedicated

from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator

_TARGETS = [
    {
        "id": "target-1",
        "type": "page",
        "url": "http://127.0.0.1/a",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-1",
    }
]


class _FlakyWs:
    """成功请求按序回复；第 N 个 Input.dispatchKeyEvent 一次性抛错；
    或第 M 次 recv 起 TimeoutError（请求无响应，传输未断）；
    或第 K 次 recv 起 ConnectionError（传输真断线）。

    recv 的 id 用 send 尝试总数（含失败那次）：session 在 send 前已自增 id。
    """

    def __init__(self, *, fail_input_once_at: int | None = None,
                 recv_timeout_at: int | None = None,
                 recv_died_at: int | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self._send_attempts = 0
        self._input_calls = 0
        self._fail_input_once_at = fail_input_once_at
        self._recv_calls = 0
        self._recv_timeout_at = recv_timeout_at
        self._recv_died_at = recv_died_at

    def send(self, payload: str) -> None:
        self._send_attempts += 1
        request = json.loads(payload)
        if request.get("method") == "Input.dispatchKeyEvent":
            self._input_calls += 1
            if self._fail_input_once_at == self._input_calls:
                self._fail_input_once_at = None  # 只失败一次
                raise OSError("boom-on-input-send")
        self.requests.append(request)

    def recv(self, timeout: float | None = None) -> str:
        self._recv_calls += 1
        # R-03（M1 修订）：ConnectionError=传输死亡证据（session.dead）；
        # TimeoutError=请求无响应（会话保留）。二者语义分离。
        if self._recv_died_at is not None and self._recv_calls >= self._recv_died_at:
            raise ConnectionError("scripted-connection-lost")
        if self._recv_timeout_at is not None and self._recv_calls >= self._recv_timeout_at:
            raise TimeoutError("scripted-recv-timeout")
        return json.dumps({"id": self._send_attempts, "result": {}})

    def close(self) -> None:
        return None


def _host(ws: _FlakyWs) -> CdpBrowserMutationActuator:
    return CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="target-1",
        http_get_json=lambda url: json.loads(json.dumps(_TARGETS)),
        ws_connect=lambda url: ws,
        attest_fn=_attest_dedicated,
    )


def _input_events(ws: _FlakyWs) -> list[tuple[str, str]]:
    return [
        (r["params"]["type"], r["params"]["key"])
        for r in ws.requests
        if r["method"] == "Input.dispatchKeyEvent"
    ]


def test_t11_partial_chord_releases_in_reverse_on_same_connection():
    """Meta↓ a↓ 成功、a↑ 投递失败 → 同连接逆序补发 a↑、Meta↑ 并带 cleanup 报告。"""
    from llm_loop.browser.cdp_action_host import _PressKeyPartialDispatchError

    ws = _FlakyWs(fail_input_once_at=3)
    with pytest.raises(_PressKeyPartialDispatchError) as excinfo:
        _host(ws).dispatch(verb="press_key", physical_target=None, args={"keys": "Meta+A"})
    cleanup = excinfo.value.cleanup
    assert cleanup["status"] == "released"
    assert cleanup["pressed"] == 2
    assert cleanup["released"] == 2
    events = _input_events(ws)
    assert events[:2] == [("keyDown", "Meta"), ("keyDown", "a")]
    assert events[2:] == [("keyUp", "a"), ("keyUp", "Meta")]  # 逆序释放
    # 只清理输入状态：除 4 个键事件外无任何其他 Input.* 投递（不重演业务键）
    assert len(events) == 4


def test_t11_dead_session_reports_input_state_unknown_without_further_sends():
    """连接真断开（R-03 语义分离后）→ 显式 input_state_unknown + 重观测路径，不再投递。"""
    from llm_loop.browser.cdp_action_host import _PressKeyPartialDispatchError

    # 第 4 次 recv＝a↑ 的应答等待中连接断开：a↑ 已发出但未确认（这正是
    # input_state_unknown 要表达的不可知性），Meta↑ 未发出。
    # R-03（M1 修订）：dead 的证据从"recv 超时"改为真传输异常——超时不再
    # 等于死亡，本契约限定于"连接确实断了"。
    ws = _FlakyWs(recv_died_at=4)
    with pytest.raises(_PressKeyPartialDispatchError) as excinfo:
        _host(ws).dispatch(verb="press_key", physical_target=None, args={"keys": "Meta+A"})
    cleanup = excinfo.value.cleanup
    assert cleanup["status"] == "input_state_unknown"
    assert cleanup["recovery"] == "reconnect_then_snapshot"
    assert cleanup["pressed"] == 2  # Meta↓、a↓（a↑ 未确认，按仍按下保守处理）
    # 死连接后没有任何新的 Input.* 投递：两次 down + 一次未确认 up，无 Meta↑
    events = _input_events(ws)
    assert events == [("keyDown", "Meta"), ("keyDown", "a"), ("keyUp", "a")]


def test_r03_keyup_timeout_with_live_connection_best_effort_release():
    """R-03 语义修正的红线：应答超时但传输未断 ≠ 死连接。

    a↑ 应答超时（弹窗/渲染阻塞）→ 会话保留 → 尽力投递 Meta↑（旧语义会因
    dead 直接跳过并误报 input_state_unknown）。释放投递的应答同样超时 →
    如实报 partial_release_failed；事件已尽力发出。
    """
    from llm_loop.browser.cdp_action_host import _PressKeyPartialDispatchError

    ws = _FlakyWs(recv_timeout_at=4)
    with pytest.raises(_PressKeyPartialDispatchError) as excinfo:
        _host(ws).dispatch(verb="press_key", physical_target=None, args={"keys": "Meta+A"})
    cleanup = excinfo.value.cleanup
    assert cleanup["status"] != "input_state_unknown"
    assert cleanup["status"] == "partial_release_failed"  # 释放应答超时，如实报
    assert cleanup["pressed"] == 2
    # 尽力释放：a↑ 重试投递已发出（与死连接场景的"零投递"形成对照）；
    # 其应答仍超时 → break，Meta↑ 不再盲试。
    assert _input_events(ws) == [
        ("keyDown", "Meta"), ("keyDown", "a"), ("keyUp", "a"), ("keyUp", "a"),
    ]


def test_t11_success_path_has_no_cleanup_side_effects():
    """守护用例：成功路径 4 个键事件、无异常（不引入回归）。"""
    ws = _FlakyWs()
    result = _host(ws).dispatch(
        verb="press_key", physical_target=None, args={"keys": "Meta+A"}
    )
    assert result.acknowledged is True
    assert _input_events(ws) == [
        ("keyDown", "Meta"),
        ("keyDown", "a"),
        ("keyUp", "a"),
        ("keyUp", "Meta"),
    ]
