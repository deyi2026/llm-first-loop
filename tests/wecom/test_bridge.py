"""企微 WS 桥测试（M0-4）：回调只入队 / 队列有界 / 干净退出无残留线程 / 单实例锁.

FakeClient 注入（零真实 WS 连接、零真实凭据）。
"""

import logging
import time
from unittest.mock import Mock

from llm_loop.wecom.bridge import _MAX_MSG_QUEUE, WeComBridge
from llm_loop.wecom.config import WeComConfig


class FakeClient:
    """aibot.WSClient 测试替身（on/connect/reply/is_connected 最小面）."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.connected = False
        self.replies: list[tuple[dict, dict]] = []
        self.connect_calls = 0
        self.disconnect_calls = 0

    def on(self, event: str, fn) -> None:
        self.handlers[event] = fn

    async def connect(self):
        self.connect_calls += 1
        self.connected = True
        return self

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False

    @property
    def is_connected(self) -> bool:
        return self.connected

    async def reply(self, frame: dict, body: dict, cmd: str | None = None) -> dict:
        self.replies.append((frame, body))
        return {"errcode": 0, "headers": frame.get("headers", {})}


class FakeHandler:
    """处理即回显（经 bridge.send_text 全链路投递）."""

    def __init__(self, bridge: WeComBridge) -> None:
        self.bridge = bridge
        self.handled: list = []

    def handle(self, msg) -> None:
        self.handled.append(msg)
        self.bridge.send_text(
            msg.req_id, msg.reply_receive_id, f"echo:{msg.text}", msg.reply_receive_id_type
        )


def _cfg() -> WeComConfig:
    return WeComConfig(bot_id="fake_bot", secret="fake_secret")


def _text_frame(req_id: str = "req_b1", text: str = "你好", chatid: str = "") -> dict:
    return {
        "cmd": "aibot_msg_callback",
        "headers": {"req_id": req_id},
        "body": {
            "msgtype": "text",
            "from": {"userid": "u_bridge"},
            "chatid": chatid,
            "chat_type": "group" if chatid else "single",
            "text": {"content": text},
        },
    }


def _make_bridge(tmp_path, client: FakeClient | None = None, handler=None) -> WeComBridge:
    client = client or FakeClient()
    bridge = WeComBridge(
        _cfg(),
        handler if handler is not None else Mock(),
        client_factory=lambda cfg: client,  # noqa: ARG005 — cfg 未用（工厂签名对齐）
        lock_path=str(tmp_path / "wecom_bridge.lock"),
    )
    return bridge


def _wait_until(pred, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def test_bridge_callback_only_enqueues(tmp_path):
    """回调只入队不跑推理：SDK 回调返回时 worker 未处理（mock 断言，零竞态）."""
    handler = Mock()
    bridge = _make_bridge(tmp_path, handler=handler)  # 未 start：无 worker 线程
    bridge._on_sdk_message(_text_frame())  # SDK loop 线程内回调（同步立即返回）
    assert handler.handle.call_count == 0  # 回调返回时未处理
    assert bridge._msg_queue.qsize() == 1  # 只入队
    # 手动消费一条（模拟 worker 语义），确认队列项是原始帧
    item = bridge._msg_queue.get_nowait()
    assert item["headers"]["req_id"] == "req_b1"


def test_bridge_queue_bounded(tmp_path):
    """队列有界：容量对齐飞书 _MAX_MSG_QUEUE=64；满后丢弃不抛异常（fail-open）."""
    bridge = _make_bridge(tmp_path)
    assert bridge._msg_queue.maxsize == _MAX_MSG_QUEUE == 64
    for i in range(_MAX_MSG_QUEUE + 5):
        bridge._on_sdk_message(_text_frame(req_id=f"req_full_{i}"))  # 不抛异常
    assert bridge._msg_queue.qsize() == _MAX_MSG_QUEUE  # 超界丢弃


def test_bridge_full_pipeline_reply_binds_req_id(tmp_path):
    """全链路：入队 → worker 解包 → handler → send_text 投递回 loop →
    FakeClient.reply 收到的 frame.headers.req_id 与来帧一致（req_id 透传链路）."""
    client = FakeClient()
    bridge = _make_bridge(tmp_path, client=client)
    handler = FakeHandler(bridge)
    bridge.attach_handler(handler)
    assert bridge.start() is True
    try:
        bridge._on_sdk_message(_text_frame(req_id="req_pipe_1", text="企微你好"))
        assert _wait_until(lambda: len(client.replies) >= 1)
        frame, body = client.replies[0]
        assert frame["headers"]["req_id"] == "req_pipe_1"  # 绑定同一次回调
        assert body["msgtype"] == "markdown"
        assert body["markdown"]["content"] == "echo:企微你好"
        assert len(handler.handled) == 1
    finally:
        bridge.stop()


def test_bridge_stop_no_residual_threads(tmp_path):
    """断开后干净退出：stop 后 loop/worker 线程均结束（无残留线程）."""
    client = FakeClient()
    bridge = _make_bridge(tmp_path, client=client)
    assert bridge.start() is True
    worker = bridge._worker_thread
    loop_thread = bridge._loop_thread
    assert worker is not None and worker.is_alive()
    assert loop_thread is not None and loop_thread.is_alive()
    bridge.stop()
    assert not worker.is_alive()  # worker 已退出
    assert not loop_thread.is_alive()  # SDK loop 线程已退出
    assert bridge._worker_thread is None and bridge._loop_thread is None
    assert client.disconnect_calls >= 1  # SDK 已断开
    # stop 幂等
    bridge.stop()


def test_bridge_single_instance_lock(tmp_path):
    """单实例锁：第二实例同锁文件启动被拒；释放后可启动（防互踢）."""
    client1, client2 = FakeClient(), FakeClient()
    lock = str(tmp_path / "wecom_bridge.lock")
    b1 = WeComBridge(_cfg(), Mock(), client_factory=lambda c: client1, lock_path=lock)  # noqa: ARG005,E501
    b2 = WeComBridge(_cfg(), Mock(), client_factory=lambda c: client2, lock_path=lock)  # noqa: ARG005,E501
    assert b1.start() is True
    try:
        assert b2.start() is False  # 锁被占用 → 拒绝启动（防新连接踢旧连接）
    finally:
        b1.stop()
    assert b2.start() is True  # 锁已释放 → 可启动
    b2.stop()


def test_bridge_disconnected_client_event(tmp_path):
    """SDK "disconnected" 客户端事件：状态更新 + 不抛异常（非人为退出→reconnecting）."""
    client = FakeClient()
    bridge = _make_bridge(tmp_path, client=client)
    assert bridge.start() is True
    try:
        bridge._on_sdk_disconnected("ConnectionClosed: 1006")
        assert bridge.state == "reconnecting"  # _stop=False：非人为退出
    finally:
        bridge.stop()
    bridge._on_sdk_disconnected("manual")  # 人为退出后：disconnected，不抛异常
    assert bridge.state == "disconnected"


def test_bridge_disconnected_event_frame_alert(tmp_path, caplog):
    """disconnected_event 事件帧（缺口 b）：识别并记 ERROR 告警（被踢下线感知）."""
    bridge = _make_bridge(tmp_path)
    frame = {
        "cmd": "aibot_event_callback",
        "headers": {"req_id": "req_evt"},
        "body": {"event": {"eventtype": "disconnected_event"}},
    }
    with caplog.at_level(logging.ERROR, logger="llm_loop.wecom.bridge"):
        bridge._on_sdk_event(frame)  # 不抛异常
    assert any("disconnected_event" in r.message for r in caplog.records)


def test_bridge_connect_failure_clean(tmp_path):
    """连接失败：清理线程与锁后返回 False（不留半启动状态）."""
    class BrokenClient(FakeClient):
        async def connect(self):
            raise RuntimeError("connect refused")

    client = BrokenClient()
    bridge = _make_bridge(tmp_path, client=client)
    assert bridge.start() is False
    assert bridge._loop_thread is None or not bridge._loop_thread.is_alive()
    assert not bridge.is_running
    # 锁已释放：新实例可启动
    b2 = _make_bridge(tmp_path)
    assert b2.start() is True
    b2.stop()
