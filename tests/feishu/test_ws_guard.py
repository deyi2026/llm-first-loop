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

    # ── P1-2-R4: 断线/重连状态 + 心跳新字段 + 历史序列 ──
    def test_reconnect_hooks_update_state(self):
        """P1-2-R4: on_reconnecting/on_reconnected 后三态 + 时间戳 + 计数如实更新."""
        c = self._connector()
        client = _SdkLikeClient()
        c._install_sdk_callbacks(client)
        assert c._conn_state == "disconnected"
        assert c._last_disconnect_ts is None
        assert c._last_reconnect_ts is None
        assert c._disconnect_count == 0
        client.on_reconnecting()
        assert c._conn_state == "reconnecting"
        assert c._last_disconnect_ts is not None
        assert c._disconnect_count == 1
        assert c._reconnect_count == 1
        client.on_reconnected()
        assert c._conn_state == "connected"
        assert c._last_reconnect_ts is not None

    def test_heartbeat_has_new_fields(self, monkeypatch):
        """P1-2-R4: 心跳 payload 含新字段且类型/取值合法."""
        import json
        from pathlib import Path

        import llm_loop.feishu.bridge as br

        c = self._connector()
        client = _SdkLikeClient()
        c._install_sdk_callbacks(client)
        client.on_reconnecting()
        c._write_heartbeat(client)
        hb = json.loads(Path(br._HEARTBEAT_PATH).read_text(encoding="utf-8"))
        assert "disconnect_count" in hb and hb["disconnect_count"] >= 1
        assert isinstance(hb["last_disconnect_ts"], float)
        assert hb["last_reconnect_ts"] is None  # 未重连完成
        assert hb["state"] in ("connected", "reconnecting", "disconnected")

    def test_heartbeat_state_transitions(self, monkeypatch):
        """P1-2-R4: 三态转换，心跳 state 字段随之变化."""
        import json
        from pathlib import Path

        import llm_loop.feishu.bridge as br

        c = self._connector()
        client = _SdkLikeClient(conn=None)
        c._write_heartbeat(client)
        hb1 = json.loads(Path(br._HEARTBEAT_PATH).read_text(encoding="utf-8"))
        assert hb1["state"] == "disconnected"
        c._conn_state = "reconnecting"
        c._write_heartbeat(client)
        hb2 = json.loads(Path(br._HEARTBEAT_PATH).read_text(encoding="utf-8"))
        assert hb2["state"] == "reconnecting"
        c._conn_state = "connected"
        c._write_heartbeat(client)
        hb3 = json.loads(Path(br._HEARTBEAT_PATH).read_text(encoding="utf-8"))
        assert hb3["state"] == "connected"

    def test_heartbeat_write_fail_open(self, monkeypatch):
        """P1-2-R4: 心跳路径不可写 → 主流程不受影响、不抛异常."""
        import llm_loop.feishu.bridge as br

        c = self._connector()
        monkeypatch.setattr(br, "_HEARTBEAT_PATH", "/nonexistent_dir_xyz/hb.json")
        monkeypatch.setattr(br, "_HEARTBEAT_HISTORY_PATH", "/nonexistent_dir_xyz/hb.jsonl")
        client = _SdkLikeClient()
        c._write_heartbeat(client)  # 不抛异常即通过

    def test_heartbeat_history_appended(self, monkeypatch, tmp_path):
        """P1-2-R4: 心跳历史追加行且与主文件一致."""
        import json
        from pathlib import Path

        import llm_loop.feishu.bridge as br

        c = self._connector()
        hist = tmp_path / "hb_history.jsonl"
        monkeypatch.setattr(br, "_HEARTBEAT_PATH", str(tmp_path / "hb.json"))
        monkeypatch.setattr(br, "_HEARTBEAT_HISTORY_PATH", str(hist))
        client = _SdkLikeClient()
        for _ in range(3):
            c._write_heartbeat(client)
        lines = hist.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        main_hb = json.loads(Path(tmp_path / "hb.json").read_text(encoding="utf-8"))
        for ln in lines:
            rec = json.loads(ln)
            assert rec["pid"] == main_hb["pid"]
            assert "ts" in rec and "state" in rec


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

    # ── P1-2-R3: levelname 同步 + 1011 匹配 ──
    def test_ping_timeout_levelname_synced(self):
        """P1-2-R3: filter 后 levelno 与 levelname 同步为 WARNING（原只改 levelno 半生效）."""
        import logging

        record = logging.LogRecord(
            name="Lark",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="receive message loop exit, err: received 3003 ping_timeout",
            args=(),
            exc_info=None,
        )
        f = _PingTimeoutDowngradeFilter()
        assert f.filter(record) is True
        assert record.levelno == logging.WARNING
        assert record.levelname == "WARNING"

    def test_keepalive_1011_downgraded(self):
        """P1-2-R3: keepalive ping timeout（1011）同样降级 + 计数."""
        import logging

        before = _PingTimeoutDowngradeFilter.count
        record = logging.LogRecord(
            name="Lark",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="sent 1011 (internal error) keepalive ping timeout",
            args=(),
            exc_info=None,
        )
        f = _PingTimeoutDowngradeFilter()
        assert f.filter(record) is True
        assert record.levelno == logging.WARNING
        assert _PingTimeoutDowngradeFilter.count == before + 1

    def test_real_event_error_not_downgraded(self):
        """P1-2-R3: 真实异常（无关键词）保持 ERROR、计数不增."""
        import logging

        before = _PingTimeoutDowngradeFilter.count
        record = logging.LogRecord(
            name="Lark",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="handle message failed, message_type: event",
            args=(),
            exc_info=None,
        )
        f = _PingTimeoutDowngradeFilter()
        assert f.filter(record) is True
        assert record.levelno == logging.ERROR
        assert record.levelname == "ERROR"
        assert _PingTimeoutDowngradeFilter.count == before

    def test_downgrade_count_increments(self):
        """P1-2-R3: 每次降级 count +1（可被心跳 ping_timeout_count 读取）."""
        import logging

        before = _PingTimeoutDowngradeFilter.count
        f = _PingTimeoutDowngradeFilter()
        for i in range(3):
            r = logging.LogRecord(
                name="Lark",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg=f"received 3003 ping_timeout #{i}",
                args=(),
                exc_info=None,
            )
            f.filter(r)
        assert _PingTimeoutDowngradeFilter.count == before + 3
