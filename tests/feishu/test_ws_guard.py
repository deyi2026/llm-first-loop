"""M47 飞书 WS 假死防护测试（2026-08-12）.

覆盖三层防护：
①_ patch_sdk_connect_lock —— lark-oapi<=1.7.2 _connect 锁泄漏根治
②看门狗 —— SDK 锁持有超时判定假死 → os._exit 自杀
③心跳落盘 —— restart_system.sh 健康检查数据源（state/reconnect 计数/锁持有）
"""

import asyncio
import time

from llm_loop.feishu.bridge import (
    _install_lark_log_filter,
    _patch_sdk_connect_lock,
    _PingTimeoutDowngradeFilter,
    _WsConnector,
)
from llm_loop.feishu.config import FeishuConfig


def _cfg() -> FeishuConfig:
    return FeishuConfig(app_id="cli_test", app_secret="secret", ws_enabled=True)


class _SdkLikeClient:
    """模拟 lark ws.Client 最小面：_lock/_conn/_connect/start + 重连钩子."""

    def __init__(self, conn=None):
        import asyncio as _aio

        self._lock = _aio.Lock()
        self._conn = conn
        self._connect_calls = 0
        self.on_reconnecting = lambda: None
        self.on_reconnected = lambda: None

    async def _connect(self):
        self._connect_calls += 1
        self._conn = object()


class TestConnectLockPatch:
    def test_conn_present_skips_without_lock_leak(self):
        """连接已建立时跳过：不重连、锁未泄漏（复现 08-12 假死根因的反面）."""
        client = _SdkLikeClient(conn=object())
        _patch_sdk_connect_lock(client)
        asyncio.run(client._connect())
        assert client._connect_calls == 0
        assert not client._lock.locked()  # 关键：原生实现此处锁泄漏永久持有

    def test_conn_absent_calls_orig(self):
        """无连接时正常走原生实现."""
        client = _SdkLikeClient(conn=None)
        _patch_sdk_connect_lock(client)
        asyncio.run(client._connect())
        assert client._connect_calls == 1
        assert client._conn is not None
        assert not client._lock.locked()

    def test_concurrent_connects_serialized(self):
        """并发重连竞态：仅首个真正连接，其余早退，锁全程无泄漏."""
        client = _SdkLikeClient(conn=None)
        _patch_sdk_connect_lock(client)

        async def _race():
            await asyncio.gather(*(client._connect() for _ in range(8)))

        asyncio.run(_race())
        assert client._connect_calls == 1
        assert not client._lock.locked()

    def test_patch_idempotent_and_mock_safe(self):
        """幂等：重复打补丁不叠加；Mock 客户端（无 _connect）静默跳过."""
        client = _SdkLikeClient()
        _patch_sdk_connect_lock(client)
        first = client._connect
        _patch_sdk_connect_lock(client)
        assert client._connect is first

        class _Bare:
            pass

        _patch_sdk_connect_lock(_Bare())  # 不抛异常即通过


class TestWatchdog:
    def _connector(self) -> _WsConnector:
        return _WsConnector(config=_cfg(), on_message=lambda _: None, has_token=lambda: True)

    def test_lock_held_duration_tracking(self):
        """锁持有时长追踪：持有计时、释放清零."""
        c = self._connector()
        client = _SdkLikeClient()
        assert c._sdk_lock_held_s(client) is None
        asyncio.run(client._lock.acquire())
        first = c._sdk_lock_held_s(client)
        assert first is not None and first >= 0
        time.sleep(0.02)
        second = c._sdk_lock_held_s(client)
        assert second > first
        client._lock.release()
        assert c._sdk_lock_held_s(client) is None

    def test_watchdog_suicide_on_stall(self, monkeypatch):
        """假死检测：锁持有超阈值 → os._exit(42) 自杀."""
        c = self._connector()
        client = _SdkLikeClient()
        asyncio.run(client._lock.acquire())  # 模拟 SDK 锁泄漏永久持有

        monkeypatch.setattr("llm_loop.feishu.bridge._WATCHDOG_LOCK_S", 0.0)
        monkeypatch.setattr("llm_loop.feishu.bridge._WATCHDOG_POLL_S", 0.01)

        exited: list[int] = []
        monkeypatch.setattr("os._exit", lambda code: exited.append(code) or c.__setattr__("_stop", True))

        import threading

        t = threading.Thread(target=c._watchdog_loop, args=(client,), daemon=True)
        t.start()
        t.join(timeout=5)
        assert exited == [42]

    def test_watchdog_no_suicide_when_healthy(self, monkeypatch):
        """健康时（锁未持有）不自杀，心跳正常落盘."""
        import json
        from pathlib import Path

        import llm_loop.feishu.bridge as br

        c = self._connector()
        client = _SdkLikeClient()
        monkeypatch.setattr(br, "_WATCHDOG_POLL_S", 0.01)

        exited: list[int] = []
        monkeypatch.setattr("os._exit", lambda code: exited.append(code))

        import threading

        t = threading.Thread(target=c._watchdog_loop, args=(client,), daemon=True)
        t.start()
        time.sleep(0.05)
        c._stop = True
        t.join(timeout=5)
        assert exited == []

        hb = json.loads(Path(br._HEARTBEAT_PATH).read_text(encoding="utf-8"))
        assert hb["pid"] > 0
        assert hb["sdk_lock_held_s"] is None
        assert "reconnect_count" in hb and "ping_timeout_count" in hb

    def test_reconnect_callback_counts(self):
        """on_reconnecting 钩子：重连计数入心跳可观测."""
        c = self._connector()
        client = _SdkLikeClient()
        c._install_sdk_callbacks(client)
        client.on_reconnecting()
        client.on_reconnecting()
        assert c._reconnect_count == 2
        c._install_sdk_callbacks(type("_Bare", (), {})())  # Mock 无属性不抛异常


class TestLogDowngrade:
    def test_ping_timeout_error_downgraded(self, caplog):
        """ping_timeout ERROR → WARNING 并计数."""
        import logging

        _install_lark_log_filter()
        before = _PingTimeoutDowngradeFilter.count
        lark_logger = logging.getLogger("Lark")
        lark_logger.error("receive message loop exit, err: received 3003 ping_timeout")
        assert _PingTimeoutDowngradeFilter.count == before + 1
        assert all(r.levelno == logging.WARNING for r in caplog.records if "ping_timeout" in r.getMessage())

    def test_filter_idempotent(self):
        import logging

        _install_lark_log_filter()
        n = len(logging.getLogger("Lark").filters)
        _install_lark_log_filter()
        assert len(logging.getLogger("Lark").filters) == n
