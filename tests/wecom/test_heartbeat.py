"""企微桥心跳文件测试（②+⑧）：字段存在、真实值、env 路径覆盖、线程干净退出.

FakeClient 注入（零真实连接、零真实凭据）；锁文件走 tmp_path（不碰
data/wecom_bridge.lock 的真实在服实例）。
"""

import json
import threading
import time
from unittest.mock import Mock

from llm_loop.wecom.bridge import WeComBridge
from llm_loop.wecom.config import WeComConfig


class FakeClient:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def on(self, event: str, fn) -> None:
        self.handlers[event] = fn

    async def connect(self):
        return self

    def disconnect(self) -> None:
        pass

    @property
    def is_connected(self) -> bool:
        return False


def _make_bridge(tmp_path) -> WeComBridge:
    return WeComBridge(
        WeComConfig(bot_id="fake_bot", secret="fake_secret"),
        Mock(),
        client_factory=lambda cfg: FakeClient(),  # noqa: ARG005
        lock_path=str(tmp_path / "wecom_bridge.lock"),
    )


def _wait_until(pred, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _read_hb(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_heartbeat_written_with_fields_and_env_override(tmp_path, monkeypatch):
    """启动即写心跳；字段齐备且为进程内可确证值；WECOM_HEARTBEAT_PATH 可覆盖路径."""
    hb_path = tmp_path / "custom" / "wecom_heartbeat.json"
    monkeypatch.setenv("WECOM_HEARTBEAT_PATH", str(hb_path))
    bridge = _make_bridge(tmp_path)
    assert bridge.start() is True
    try:
        assert _wait_until(lambda: hb_path.is_file()), "心跳文件启动即写入"
        hb = _read_hb(hb_path)
        # 必备字段（service_control 空闲判定 + 观测字段）全部存在且类型正确
        assert set(hb) >= {
            "ts", "pid", "state", "reconnect_count", "error_count",
            "last_authenticated_ts", "last_disconnect_ts", "last_disconnect_reason",
            "kick_pending", "processing_msg_id", "queue_depth",
        }
        assert isinstance(hb["ts"], float)
        assert hb["pid"] > 0
        assert hb["state"] in {"disconnected", "connected", "authenticated", "reconnecting"}
        assert hb["reconnect_count"] == 0 and hb["error_count"] == 0
        assert hb["processing_msg_id"] == "" and hb["queue_depth"] == 0
        assert hb["kick_pending"] is False
    finally:
        bridge.stop()
    # 优雅停止后终态落盘：state=disconnected（此后文件陈旧 → 健康检查判死）
    assert _read_hb(hb_path)["state"] == "disconnected"


def test_heartbeat_reflects_real_callback_facts(tmp_path, monkeypatch):
    """心跳字段来自真实 SDK 回调（authenticated/reconnecting/disconnected/error）."""
    hb_path = tmp_path / "hb.json"
    monkeypatch.setenv("WECOM_HEARTBEAT_PATH", str(hb_path))
    bridge = _make_bridge(tmp_path)
    assert bridge.start() is True
    try:
        bridge._on_sdk_authenticated()
        bridge._on_sdk_reconnecting(1)
        bridge._on_sdk_disconnected("ConnectionClosed: 1006")
        bridge._on_sdk_error(ValueError("boom"))
        bridge._write_heartbeat()
        hb = _read_hb(hb_path)
        assert hb["state"] == "reconnecting"
        assert hb["reconnect_count"] == 1
        assert hb["error_count"] == 1
        assert "boom" in (hb["last_error"] or "")
        assert hb["last_authenticated_ts"] is not None
        assert hb["last_disconnect_ts"] is not None
        assert "1006" in hb["last_disconnect_reason"]
    finally:
        bridge.stop()


def test_heartbeat_kick_pending_intermediate_state(tmp_path, monkeypatch):
    """踢线中间态：disconnected_event 先到、连接层断开未到 → kick_pending=True."""
    hb_path = tmp_path / "hb.json"
    monkeypatch.setenv("WECOM_HEARTBEAT_PATH", str(hb_path))
    bridge = _make_bridge(tmp_path)
    assert bridge.start() is True
    try:
        kick_frame = {
            "cmd": "aibot_event_callback",
            "body": {"event": {"eventtype": "disconnected_event"}},
        }
        bridge._on_sdk_event(kick_frame)  # 服务端已宣布踢线（旧连接关闭有延迟）
        bridge._write_heartbeat()
        hb = _read_hb(hb_path)
        assert hb["kick_pending"] is True and hb["last_kick_ts"] is not None
        bridge._on_sdk_disconnected("closed")  # 连接层真正断开 → 闭环
        bridge._write_heartbeat()
        assert _read_hb(hb_path)["kick_pending"] is False
    finally:
        bridge.stop()


def test_heartbeat_thread_clean_exit(tmp_path, monkeypatch):
    """stop 后心跳线程结束（无残留线程）。"""
    monkeypatch.setenv("WECOM_HEARTBEAT_PATH", str(tmp_path / "hb.json"))
    bridge = _make_bridge(tmp_path)
    assert bridge.start() is True
    thread = bridge._heartbeat_thread
    assert thread is not None and thread.is_alive()
    bridge.stop()
    assert not thread.is_alive()
    assert bridge._heartbeat_thread is None


def test_heartbeat_processing_msg_id_tracks_worker(tmp_path, monkeypatch):
    """processing_msg_id 是 worker 处理中标识的真实值（req_id），处理完清空."""
    monkeypatch.setenv("WECOM_HEARTBEAT_PATH", str(tmp_path / "hb.json"))
    bridge = _make_bridge(tmp_path)
    assert bridge.start() is True
    try:
        release = threading.Event()

        def slow_handler(msg):  # noqa: ARG001 — 签名对齐
            release.wait(timeout=5)

        bridge.attach_handler(type("H", (), {"handle": staticmethod(slow_handler)})())
        frame = {
            "cmd": "aibot_msg_callback",
            "headers": {"req_id": "req_proc_1"},
            "body": {"msgtype": "text", "from": {"userid": "u"}, "text": {"content": "hi"}},
        }
        bridge._on_sdk_message(frame)
        assert _wait_until(lambda: bridge._processing_msg_id == "req_proc_1")
        bridge._write_heartbeat()
        assert _read_hb(tmp_path / "hb.json")["processing_msg_id"] == "req_proc_1"
        release.set()
        assert _wait_until(lambda: bridge._processing_msg_id == "")
    finally:
        release.set()
        bridge.stop()
