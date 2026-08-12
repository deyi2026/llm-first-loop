"""重启优雅性守护测试（P0 维护标记 + P1 优雅退出 + P2 停所有/回写 PID）.

守护目标: 防止重启脚本退回「竞态抢跑 + SIGKILL 强杀 + PID 文件缺失」的旧缺陷。

断言:
1. restart_system.sh 含 maintenance.lock 维护标记（touch/rm）—— P0
2. guard_system.sh 含 maintenance.lock 检查 + skip_maintenance（跳过拉起）—— P0
3. restart_system.sh 的 _stop_service 用 pgrep/pkill 停所有匹配进程 —— P2
4. restart_system.sh 的 _start_service「已运行」分支回写 PID 文件 —— P2
5. web/__init__.py 含 timeout_graceful_shutdown（< GRACE_S）—— P1
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class TestMaintenanceLock:
    def test_restart_touches_maintenance_lock(self):
        text = _read("scripts/restart_system.sh")
        assert "MAINTENANCE_LOCK" in text
        assert "maintenance.lock" in text
        assert "touch \"$MAINTENANCE_LOCK\"" in text
        assert "rm -f \"$MAINTENANCE_LOCK\"" in text

    def test_guard_skips_on_maintenance(self):
        text = _read("scripts/guard_system.sh")
        assert "maintenance.lock" in text
        assert "skip_maintenance" in text


class TestStopAllProcesses:
    def test_stop_service_uses_pgrep_pkill(self):
        text = _read("scripts/restart_system.sh")
        assert "pids=\"$(pgrep -f" in text
        assert "pkill -9 -f" in text


class TestPidWriteBack:
    def test_start_service_writes_back_pid(self):
        text = _read("scripts/restart_system.sh")
        assert "回写 PID" in text
        assert 'echo "$running_pid" > "$DATA_DIR/${svc}.pid"' in text


class TestWebGracefulShutdown:
    def test_uvicorn_graceful_shutdown(self):
        text = _read("src/llm_loop/web/__init__.py")
        assert "timeout_graceful_shutdown" in text
