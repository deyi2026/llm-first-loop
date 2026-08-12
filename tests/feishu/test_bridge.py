"""飞书 WS 桥测试（M42，用例 1-5）.

启用条件 / 事件去重（窗口有界）/ 凭证预检（格式+凭证+网络不可达不阻断）/ 断线重连（指数退避+长退避+状态）/ 生命周期。
Mock _WsConnector + 构造 receive_v1 事件负载，零真实 WS 连接、零真实飞书 API（token 预检注入 Mock）。
"""

import json
from unittest.mock import Mock

import httpx

from llm_loop.feishu.bridge import FeishuWsBridge, _backoff_delay
from llm_loop.feishu.config import FeishuConfig


def _cfg(
    app_id: str = "cli_ab12cd34", secret: str = "sec", ws_enabled: bool = True
) -> FeishuConfig:
    return FeishuConfig(app_id=app_id, app_secret=secret, ws_enabled=ws_enabled)


def _receive_event(
    event_id: str = "evt_1",
    message_id: str = "om_1",
    open_id: str = "ou_test",
    chat_id: str = "oc_test",
    msg_type: str = "text",
    text: str = "你好",
    sender_type: str = "user",
) -> dict:
    content = json.dumps({"text": text}) if msg_type == "text" else "{}"
    return {
        "header": {"event_type": "im.message.receive_v1", "event_id": event_id},
        "event": {
            "sender": {"sender_id": {"open_id": open_id}, "sender_type": sender_type},
            "message": {"message_id": message_id, "message_type": msg_type, "content": content},
            "chat": {"chat_id": chat_id, "chat_type": "p2p"},
        },
    }


def _make_bridge(monkeypatch, config=None, handler=None):
    bridge = FeishuWsBridge(config or _cfg(), handler if handler is not None else Mock())
    monkeypatch.setattr(bridge, "_token_probe", lambda: None)  # 防真实网络
    return bridge


def test_ws_bridge_enable_condition(monkeypatch):
    """用例 1：无凭证 / FEISHU_WS_ENABLED=0 不启动；条件满足启动."""
    # a) 无 FEISHU_APP_ID/SECRET → start() False + 如实提示（不伪装已启用）
    bridge = _make_bridge(monkeypatch, config=_cfg(app_id="", secret=""))
    assert bridge.start() is False
    assert bridge.is_healthy() is False

    # a) FEISHU_WS_ENABLED=0 → 不启动
    bridge = _make_bridge(monkeypatch, config=_cfg(ws_enabled=False))
    assert bridge.start() is False

    # b) 条件满足 → start() True + 连接循环启动（守护线程存活）
    bridge = _make_bridge(monkeypatch)
    assert bridge.start() is True
    assert bridge.is_healthy() is True
    assert bridge.state == "connected"
    bridge.stop()
    assert bridge.is_healthy() is False


def test_ws_bridge_dedup(monkeypatch):
    """用例 2：相同事件仅处理一次 + 不同事件均处理 + 去重窗口有界."""
    handler = Mock()
    bridge = _make_bridge(monkeypatch, handler=handler)

    payload = _receive_event(event_id="evt_same", message_id="om_same")
    bridge._on_ws_message(payload)
    bridge._on_ws_message(payload)  # 重复推送（相同 event_id）
    bridge._on_ws_message(_receive_event(event_id="evt_diff", message_id="om_diff"))
    assert handler.handle.call_count == 2  # a) 相同仅一次 b) 不同均处理

    # c) 去重窗口有界（超 500 上限旧 id 被淘汰）
    for i in range(501):
        bridge._is_new_event(f"evt_bulk_{i}")
    assert bridge._is_new_event("evt_bulk_0") is True  # 最旧已被淘汰
    assert bridge._is_new_event("evt_bulk_500") is False  # 最新仍去重


def test_ws_bridge_preflight(monkeypatch):
    """用例 3：app_id 格式异常拒绝 + 凭证失败拒绝 + 网络不可达仍尝试启动."""
    # a) app_id 格式异常 → 拒绝启动 + 如实提示
    bridge = _make_bridge(monkeypatch, config=_cfg(app_id="not_cli_format"))
    reason = bridge._preflight()
    assert reason is not None
    assert "格式异常" in reason
    assert bridge.start() is False

    # b) 凭证校验失败（Mock 返回错误 code）→ 拒绝启动 + 提示 code/msg
    bridge = _make_bridge(monkeypatch)
    monkeypatch.setattr(bridge, "_token_probe", lambda: "凭证校验失败（code=99999 msg=invalid）")
    assert bridge.start() is False
    assert "99999" in bridge._preflight()

    # c) 网络不可达（httpx 抛异常）→ 预检不阻断（返回 None）+ 仍尝试启动
    bridge = _make_bridge(monkeypatch)

    def _boom_post(*args, **kwargs):
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr("llm_loop.feishu.bridge.httpx.post", _boom_post)
    assert bridge._token_probe() is None  # 网络异常 → None（不阻断）
    assert bridge._preflight() is None
    monkeypatch.setattr(bridge, "_token_probe", lambda: None)
    assert bridge.start() is True
    bridge.stop()


def test_ws_bridge_reconnect(monkeypatch):
    """用例 4：指数退避序列 5/10/20/30/30 + 超限长退避 300 + 断线重连 + 状态如实."""
    # b) 退避序列
    assert [_backoff_delay(i) for i in range(1, 6)] == [5, 10, 20, 30, 30]
    # c) 连续失败超限（>5 次）→ 长退避 300s（不高频重试）
    assert _backoff_delay(6) == 300
    assert _backoff_delay(10) == 300

    # a) 断线 → 自动重连（Mock 连接器首次断开，第二次恢复后退出）
    class _FakeConnector:
        def __init__(self, bridge):
            self._bridge = bridge
            self.calls = 0

        def run(self):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("simulated disconnect")
            self._bridge._running = False

        def stop(self):
            pass

    bridge = _make_bridge(monkeypatch)
    fake = _FakeConnector(bridge)
    bridge._connector = fake
    bridge._running = True
    bridge._ws_state = "connected"
    monkeypatch.setattr("llm_loop.feishu.bridge._sleep", lambda s: None)
    bridge._run_loop()
    assert fake.calls == 2  # 断线后自动重连
    assert bridge.state == "disconnected"

    # d) 状态如实：异常时 reconnecting（_sleep 观察点捕获）
    class _AlwaysFail:
        calls = 0

        def run(self):
            _AlwaysFail.calls += 1
            raise ConnectionError("boom")

        def stop(self):
            pass

    bridge2 = _make_bridge(monkeypatch)
    bridge2._connector = _AlwaysFail()
    bridge2._running = True
    states_at_sleep: list[str] = []

    def _sleep_observe(s):
        states_at_sleep.append(bridge2.state)
        bridge2._running = False

    monkeypatch.setattr("llm_loop.feishu.bridge._sleep", _sleep_observe)
    bridge2._run_loop()
    assert states_at_sleep == ["reconnecting"]


def test_ws_bridge_lifecycle(monkeypatch):
    """用例 5：start/stop/is_healthy 全生命周期（Mock 连接器 + 守护线程）."""
    bridge = _make_bridge(monkeypatch)
    assert bridge.start() is True  # a) start() 返回如实
    assert bridge.is_healthy() is True  # b) 运行中 True
    assert bridge.state == "connected"
    bridge.stop()  # c) stop() 后线程退出 + 状态停止
    assert bridge.is_healthy() is False
    assert bridge.state == "disconnected"
    assert bridge._thread is None or not bridge._thread.is_alive()

    # 条件不满足 → start() False（如实）
    bridge2 = _make_bridge(monkeypatch, config=_cfg(app_id="", secret=""))
    assert bridge2.start() is False
    assert bridge2.is_healthy() is False


# ── M65: EVO-20260811-cf6d9a78 验证闭环（no-op 处理器注册断言）──


def test_event_handler_registers_noop_processors(monkeypatch):
    """_build_event_handler 注册 4 类已知无需处理事件的 no-op 处理器（消日志噪音）."""
    import lark_oapi as lark

    registered: list[str] = []

    class _FakeBuilder:
        def register_p2_im_message_receive_v1(self, fn):
            registered.append("receive")
            return self

        def register_p2_im_message_message_read_v1(self, fn):
            registered.append("message_read")
            return self

        def register_p2_im_message_reaction_created_v1(self, fn):
            registered.append("reaction_created")
            return self

        def register_p2_im_message_reaction_deleted_v1(self, fn):
            registered.append("reaction_deleted")
            return self

        def register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(self, fn):
            registered.append("access_event")
            return self

        def build(self):
            return "handler"

    class _FakeDispatcher:
        @staticmethod
        def builder(app_id, app_secret):
            return _FakeBuilder()

    monkeypatch.setattr(lark, "EventDispatcherHandler", _FakeDispatcher)
    from unittest.mock import Mock

    from llm_loop.feishu.bridge import _WsConnector

    bridge = _WsConnector(config=_cfg(), on_message=Mock(), has_token=lambda: True)
    handler = bridge._build_event_handler()
    assert handler == "handler"
    # 已读回执 / 表情创建 / 表情删除 / 进入会话 均注册 no-op（cf6d9a78）
    for expected in ("message_read", "reaction_created", "reaction_deleted", "access_event"):
        assert expected in registered, f"{expected} 未注册 no-op 处理器"
    # 消息接收仍走真实处理
    assert "receive" in registered
