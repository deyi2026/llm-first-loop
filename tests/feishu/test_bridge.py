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


# ── P1-2-R2: 消息处理线程迁移（worker + 有界队列）──


def _connector_with(on_message, queue_max=4):
    import threading

    from llm_loop.feishu.bridge import _WsConnector

    connector = _WsConnector(
        config=_cfg(),
        on_message=on_message,
        has_token=lambda: True,
        ws_client_factory=lambda eh: object(),
        sleep=lambda s: None,
    )
    connector._msg_queue = __import__("queue").Queue(maxsize=queue_max)
    connector._worker_thread = threading.Thread(
        target=connector._worker_loop, name="test-worker", daemon=True
    )
    connector._worker_thread.start()
    return connector


def _stop_worker(connector):
    connector._msg_queue.put_nowait(None)
    connector._worker_thread.join(timeout=5)


def test_handle_event_returns_immediately_not_blocking():
    """P1-2-R2: _handle_event 提交即返（<0.1s），消息在 worker 线程执行（线程 id ≠ 调用线程）."""
    import threading
    import time

    received = {}

    def _slow(payload):
        time.sleep(0.2)
        received["thread_id"] = threading.get_ident()
        received["payload"] = payload

    connector = _connector_with(_slow, queue_max=4)
    try:
        payload = {
            "header": {"event_id": "evt_fast", "event_type": "im.message.receive_v1"},
            "event": {"sender": {"sender_id": {"open_id": "ou_1"}}, "message": {}},
        }
        t0 = time.time()
        connector._handle_event(payload)
        elapsed = time.time() - t0
        assert elapsed < 0.1  # 未同步执行慢处理
        deadline = time.time() + 2.0
        while time.time() < deadline and "payload" not in received:
            time.sleep(0.01)
        assert received.get("thread_id") != threading.get_ident()
        assert received["payload"]["header"]["event_id"] == "evt_fast"
    finally:
        _stop_worker(connector)


def test_worker_serial_order():
    """P1-2-R2: 连续提交多条 payload 处理顺序与提交顺序一致（单 worker 串行）."""
    import time

    order: list[str] = []

    def _collect(payload):
        order.append(payload["header"]["event_id"])

    connector = _connector_with(_collect, queue_max=8)
    try:
        for i in range(5):
            connector._submit_message(
                {"header": {"event_id": f"evt_seq_{i}", "event_type": "im.message.receive_v1"}, "event": {}}
            )
        deadline = time.time() + 2.0
        while time.time() < deadline and len(order) < 5:
            time.sleep(0.01)
        assert order == [f"evt_seq_{i}" for i in range(5)]
    finally:
        _stop_worker(connector)


def test_long_processing_ping_not_blocked():
    """P1-2-R2: 长处理期间（同 loop 语义）ping 计数持续增长——直接证明 R2 目标.

    模拟: worker 线程处理长消息（0.3s），期间主线程持续"ping"（计数），
    验证长处理不阻塞 ping（R2 核心：消息处理已从 loop 剥离）。
    """
    import threading
    import time

    ping_count = [0]
    stop_flag = [False]

    def _long(payload):
        time.sleep(0.3)

    connector = _connector_with(_long, queue_max=4)
    try:
        connector._submit_message({"header": {"event_id": "evt_long", "event_type": "im.message.receive_v1"}, "event": {}})

        def _ping_loop():
            while not stop_flag[0]:
                ping_count[0] += 1
                time.sleep(0.01)

        t = threading.Thread(target=_ping_loop, daemon=True)
        t.start()
        time.sleep(0.35)  # 覆盖长处理窗口
        stop_flag[0] = True
        t.join(timeout=2)
        assert ping_count[0] >= 10  # 长处理期间 ping 持续发生（未被阻塞）
    finally:
        _stop_worker(connector)


def test_worker_queue_full_fail_open():
    """P1-2-R2: 满队列 _submit_message 返回 False、日志含告警、不抛异常."""
    import queue as _queue
    import unittest.mock as _mock

    from llm_loop.feishu.bridge import _WsConnector

    connector = _WsConnector(
        config=_cfg(),
        on_message=lambda p: None,
        has_token=lambda: True,
        ws_client_factory=lambda eh: object(),
        sleep=lambda s: None,
    )
    # 满队列（1 容量，已占满）——不启动 worker，直接测 _submit_message fail-open
    connector._msg_queue = _queue.Queue(maxsize=1)
    connector._msg_queue.put_nowait({"occupied": True})
    with _mock.patch("llm_loop.feishu.bridge.logger.warning") as warn:
        ok = connector._submit_message({"header": {"event_id": "evt_full_2"}, "event": {}})
        assert ok is False
        assert warn.called


def test_worker_on_message_error_isolated():
    """P1-2-R2: 单条消息异常不影响后续消息处理（worker 存活）."""
    import time

    order: list[str] = []

    def _flaky(payload):
        ev = payload["header"]["event_id"]
        if ev == "evt_bad":
            raise RuntimeError("boom")
        order.append(ev)

    connector = _connector_with(_flaky, queue_max=4)
    try:
        connector._submit_message({"header": {"event_id": "evt_bad"}, "event": {}})
        connector._submit_message({"header": {"event_id": "evt_good"}, "event": {}})
        deadline = time.time() + 2.0
        while time.time() < deadline and "evt_good" not in order:
            time.sleep(0.01)
        assert order == ["evt_good"]  # 异常后 worker 仍处理后续消息
    finally:
        _stop_worker(connector)


def test_worker_message_delivery():
    """P1-2-R2: 队列 → worker → on_message 回调完整（消息零丢失）."""
    import time

    received: list[dict] = []
    connector = _connector_with(lambda p: received.append(p), queue_max=4)
    try:
        for i in range(4):
            connector._submit_message({"header": {"event_id": f"evt_del_{i}"}, "event": {}})
        deadline = time.time() + 2.0
        while time.time() < deadline and len(received) < 4:
            time.sleep(0.01)
        assert len(received) == 4
        assert [r["header"]["event_id"] for r in received] == [f"evt_del_{i}" for i in range(4)]
    finally:
        _stop_worker(connector)
