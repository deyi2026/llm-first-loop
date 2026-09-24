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
        """2026-09-24 更新：强杀改按 PID 列表（kill -9 $pid）——pkill -f
        依赖 argv 模式，模式失明即杀不到（双面探针修复的同一根因），且
        模式过宽有误杀主区风险。pgrep 双面发现 + PID 定点强杀是契约。"""
        text = _read("scripts/restart_system.sh")
        assert "pgrep -f" in text          # 发现仍用 pgrep（双面模式）
        assert "pkill -9 -f" not in text   # 强杀不再走全局模式
        assert "kill -9 \"$p\"" in text or "kill -9 $p" in text  # 按 PID 定点

    def test_stop_service_is_scoped_to_current_workspace(self):
        """镜像 stop/restart 不得泛匹配同名模块，必须限定 PROJECT_DIR.

        2026-09-24 更新：双面探针（runtime.launch 新面 + llm_loop.<svc>
        旧面）均以 PROJECT_DIR 锚定；web 附加端口兜底 PID 亦校验命令行
        含 PROJECT_DIR（防误杀主区 8902/无关占用者）。"""
        text = _read("scripts/restart_system.sh")
        start = text.index("_stop_service()")
        end = text.index("# ── 运行日志轮转", start)
        block = text[start:end]
        assert 'local pattern_new="$PROJECT_DIR/.venv/bin/python -m llm_loop' in block
        assert 'local pattern_old="$PROJECT_DIR/.venv/bin/python -m llm_loop' in block
        assert 'local pattern="llm_loop' not in block
        # 端口兜底 PID 必须锚定 PROJECT_DIR 校验后才 kill
        assert block.index('grep -q "$PROJECT_DIR"') < block.index("kill")


class TestPidWriteBack:
    def test_start_service_writes_back_pid(self):
        text = _read("scripts/restart_system.sh")
        assert "回写 PID" in text
        assert 'echo "$running_pid" > "$DATA_DIR/${svc}.pid"' in text


class TestWebGracefulShutdown:
    def test_uvicorn_graceful_shutdown(self):
        text = _read("src/llm_loop/web/__init__.py")
        assert "timeout_graceful_shutdown" in text
