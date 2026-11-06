# R-03（M1 修订批次，外部审查 2026-11-06 复核 §4）：请求超时 ≠ 会话死亡。
"""红→绿契约：基线 5e295e1e0 上失败——timeout 标 dead 导致 dialog 恢复时
_ensure_session 关闭原连接、新建连接先发 Page.enable 又被同一弹窗阻塞，
Page.handleJavaScriptDialog 永远发不出（dispatch 层 R1 "session kept" 的
正确设计被底层 dead 标记架空）。

协议替身：_DialogBlockedWs 模拟同步弹窗持有 renderer——常规命令无响应
（recv 立即 TimeoutError），仅 Page.handleJavaScriptDialog 立即回响应。
对照实验（审查 §3.2）：仅保留同一有效 socket 不标传输死亡时，同连接
handle 成功——本文件将该对照固化为回归。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest
from test_browser_presskey_release_v01 import _attest_dedicated

from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator

_TARGETS = [
    {
        "id": "target-1",
        "type": "page",
        "url": "http://127.0.0.1/a",
        "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/target-1",
    }
]


class _DialogBlockedWs:
    """renderer 被同步弹窗阻塞：常规命令无响应；handle 立即响应。"""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.pending: list[str] = []

    def send(self, payload: str) -> None:
        req = json.loads(payload)
        self.requests.append(req)
        # 真实序列建模：attach 后 Page.enable 正常成功（renderer 尚未被弹窗
        # 卡住），随后动作命令应答被阻塞，仅 handle 立即回响应。
        if req["method"] in ("Page.handleJavaScriptDialog", "Page.enable"):
            self.pending.append(json.dumps({"id": req["id"], "result": {}}))

    def recv(self, timeout: float | None = None):  # noqa: ARG002
        if self.pending:
            return self.pending.pop(0)
        raise TimeoutError("dialog-blocked-renderer")

    def close(self) -> None:
        return None


def _actuator(ws: _DialogBlockedWs):
    counter = {"connects": 0}

    def ws_connect(url: str) -> _DialogBlockedWs:  # noqa: ARG001
        counter["connects"] += 1
        return ws

    actuator = CdpBrowserMutationActuator(
        "http://127.0.0.1:9222",
        target_id="target-1",
        http_get_json=lambda url: json.loads(json.dumps(_TARGETS)),
        ws_connect=ws_connect,
        attest_fn=_attest_dedicated,
    )
    return actuator, counter


def test_r03_dialog_recoverable_on_same_connection_after_timeout() -> None:
    ws = _DialogBlockedWs()
    actuator, counter = _actuator(ws)
    # 1) 请求超时：renderer 被弹窗阻塞，第一个 keyDown 应答无响应 →
    #    组合键未按下任何键即失败（cause=TimeoutError，副作用 unknown）
    with pytest.raises(RuntimeError, match="partial dispatch"):
        actuator.dispatch(verb="press_key", physical_target=None, args={"keys": "Enter"})
    assert counter["connects"] == 1
    # 2) timeout 之后真实再调 dialog（不是只断言 session 对象非空）——
    #    原连接上的 Page.handleJavaScriptDialog 必须可达且成功。
    result = actuator.dispatch(verb="dialog", physical_target=None, args={"action": "accept"})
    assert result.acknowledged is True
    assert counter["connects"] == 1, "timeout 不得触发连接重建（弹窗唯一恢复出口被切断）"
    assert any(
        r["method"] == "Page.handleJavaScriptDialog" for r in ws.requests
    ), "handle 命令必须真实发出"


def test_r03_timeout_does_not_mark_session_dead() -> None:
    ws = _DialogBlockedWs()
    actuator, _counter = _actuator(ws)
    with pytest.raises(RuntimeError, match="partial dispatch"):
        actuator.dispatch(verb="press_key", physical_target=None, args={"keys": "Enter"})
    session = actuator._session
    assert session is not None
    assert session.dead is False, "请求超时≠传输死亡；副作用 unknown 但会话保留给恢复路径"
