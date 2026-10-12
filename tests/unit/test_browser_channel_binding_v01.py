"""S3a：BrowserChannelBinding 共享绑定身份（DESIGN-20261005 v4 §4.3，v4-G3）。

1. extract_browser_ws_uuid / coordinator 纯逻辑
2. 感知 host 与 actuator 共享协调器：同实例放行、跨实例（uuid 不同）拒绝
3. coordinator=None ⇒ 两 host 首绑行为与 S3a 之前一致（TCP 行为不变约束）
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from llm_loop.browser.cdp_action_host import CdpBrowserMutationActuator
from llm_loop.browser.cdp_host import CdpReadOnlyBrowserHost
from llm_loop.browser.channel_binding import (
    BrowserChannelBindingCoordinator,
    extract_browser_ws_uuid,
)


def _attest_dedicated(url: str):  # noqa: ANN001, ANN202 - S3b 测试桩
    from llm_loop.browser.attestation import AttestationVerdict
    return AttestationVerdict(
        verdict="dedicated", user_data_dir="/tmp/attest-stub-profile",
        argv_sha256="stub" * 16, argv=(), detail="unit-test stub",
    )


# ── 1. 纯逻辑 ────────────────────────────────────────────────────────────


def test_extract_browser_ws_uuid_ok():
    url = "ws://127.0.0.1:9222/devtools/browser/0a1b2c3d-e4f5"
    assert extract_browser_ws_uuid(url) == "0a1b2c3d-e4f5"


@pytest.mark.parametrize("url", ["", "ws://127.0.0.1:9222/devtools/page/xyz", "ws://127.0.0.1:9222/devtools/browser/"])
def test_extract_browser_ws_uuid_rejects(url):
    with pytest.raises(RuntimeError):
        extract_browser_ws_uuid(url)


def test_coordinator_first_establish_then_match():
    c = BrowserChannelBindingCoordinator()
    b1 = c.require_match("uuid-1", "t-1", "ws://127.0.0.1:9222/devtools/page/t-1")
    assert c.binding is b1
    b2 = c.require_match("uuid-1", "t-1", "ws://127.0.0.1:9222/devtools/page/t-1")
    assert b2 is b1


@pytest.mark.parametrize(
    "uuid,tid,ws",
    [
        ("uuid-OTHER", "t-1", "ws://127.0.0.1:9222/devtools/page/t-1"),
        ("uuid-1", "t-OTHER", "ws://127.0.0.1:9222/devtools/page/t-1"),
        ("uuid-1", "t-1", "ws://127.0.0.1:9222/devtools/page/t-OTHER"),
    ],
)
def test_coordinator_mismatch_refuses(uuid, tid, ws):
    c = BrowserChannelBindingCoordinator()
    c.require_match("uuid-1", "t-1", "ws://127.0.0.1:9222/devtools/page/t-1")
    with pytest.raises(RuntimeError, match="binding mismatch"):
        c.require_match(uuid, tid, ws)


# ── 2. 两 host 共享协调器 ────────────────────────────────────────────────


class _FakeWs:
    def __init__(self) -> None:
        self.pending: list[str] = []
        self.closed = False

    def send(self, payload: str) -> None:
        req = json.loads(payload)
        method = req["method"]
        if method == "DOM.resolveNode":
            result = {"result": {"object": {"objectId": "obj-1"}}}
        elif method == "Runtime.callFunctionOn" or method == "Runtime.evaluate":
            result = {"result": {"result": {"type": "undefined"}}}
        elif method == "Page.enable":
            result = {"result": {}}
        elif method == "Target.getTargetInfo":
            result = {"result": {"targetInfo": {"targetId": req["params"].get("targetId")}}}
        else:
            raise AssertionError(method)
        self.pending.append(json.dumps({"id": req["id"], **result}))

    def recv(self, timeout: float | None = None) -> str:  # noqa: ARG002
        return self.pending.pop(0)

    def close(self) -> None:
        self.closed = True


def _make_targets(target_id: str, port: int) -> list[dict[str, Any]]:
    return [{
        "id": target_id, "type": "page", "url": "about:blank",
        "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/page/{target_id}",
    }]


def _perception_host(coord, target_id="t-1", uuid="uuid-A", port=9222):
    ws = _FakeWs()
    host = CdpReadOnlyBrowserHost(
        f"http://127.0.0.1:{port}",
        target_id=target_id,
        http_get_json=lambda url: json.loads(json.dumps(_make_targets(target_id, port))),
        http_get_version_dict=lambda url: {
            "Browser": "Chrome/154",
            "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/{uuid}",
        },
        ws_connect=lambda url: ws,
        binding_coordinator=coord,
        attest_fn=_attest_dedicated,
    )
    return host


def _actuator(coord, target_id="t-1", uuid="uuid-A", port=9222):
    ws = _FakeWs()
    host = CdpBrowserMutationActuator(
        f"http://127.0.0.1:{port}",
        target_id=target_id,
        http_get_json=lambda url: json.loads(json.dumps(_make_targets(target_id, port))),
        http_get_version_dict=lambda url: {
            "Browser": "Chrome/154",
            "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/browser/{uuid}",
        },
        ws_connect=lambda url: ws,
        binding_coordinator=coord,
        attest_fn=_attest_dedicated,
    )
    return host


def test_two_hosts_same_instance_shared_binding_passes():
    coord = BrowserChannelBindingCoordinator()
    perceive = _perception_host(coord)
    actuate = _actuator(coord)
    perceive.probe_page_target()
    actuate.dispatch(verb="scroll", physical_target="dom:1", args={"delta_pages": 1})
    assert coord.binding is not None
    assert coord.binding.browser_ws_uuid == "uuid-A"


def test_actuator_on_different_chrome_instance_refused():
    """感知已绑定 uuid-A 的 Chrome；actuator 的端口背后换成了 uuid-B 的 Chrome ⇒ 拒绝。"""
    coord = BrowserChannelBindingCoordinator()
    perceive = _perception_host(coord, uuid="uuid-A")
    perceive.probe_page_target()
    assert coord.binding.browser_ws_uuid == "uuid-A"
    actuate = _actuator(coord, target_id="t-9", uuid="uuid-B", port=9333)
    with pytest.raises(RuntimeError, match="binding mismatch"):
        actuate.dispatch(verb="scroll", physical_target="dom:1", args={"delta_pages": 1})


def test_perception_second_chrome_instance_refused_after_actuator_bound():
    coord = BrowserChannelBindingCoordinator()
    actuate = _actuator(coord, target_id="t-1", uuid="uuid-B")
    actuate.dispatch(verb="scroll", physical_target="dom:1", args={"delta_pages": 1})
    perceive = _perception_host(coord, target_id="t-7", uuid="uuid-C", port=9444)
    with pytest.raises(RuntimeError, match="binding mismatch"):
        perceive.probe_page_target()


# ── 3. coordinator=None 行为不变 ─────────────────────────────────────────


def test_no_coordinator_behavior_unchanged():
    perceive = _perception_host(None)
    info = perceive.probe_page_target()
    assert info["target_id"] == "t-1"
    actuate = _actuator(None, target_id="t-8", uuid="uuid-Z", port=9555)
    actuate.dispatch(verb="scroll", physical_target="dom:1", args={"delta_pages": 1})
