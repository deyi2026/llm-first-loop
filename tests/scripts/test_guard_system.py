"""P1-3-R4: guard_system.sh 守护脚本静态断言测试.

沿项目静态断言风格（读取脚本文本断言），验证:
- 复用 restart_system.sh 幂等 start/status 入口
- 指数退避（防重启风暴）
- mkdir 原子锁防多实例（macOS 无 flock，用 POSIX 兼容方案）
- guard.log 动作记录
- 不含 kill -9 等强杀健康进程逻辑（程序最小化）
"""

from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "guard_system.sh"


def test_guard_script_exists():
    assert _SCRIPT.exists()
    assert _SCRIPT.stat().st_size > 0


def test_guard_reuses_restart_system():
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "restart_system.sh" in text
    assert "start" in text
    assert "status" in text


def test_guard_backoff():
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "GUARD_MAX_BACKOFF_S" in text
    assert "GUARD_BACKOFF_BASE_S" in text
    assert "backoff" in text


def test_guard_mkdir_lock():
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "mkdir" in text  # mkdir 原子锁（macOS POSIX 兼容防多实例）
    assert "guard.lock" in text


def test_guard_action_log():
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "guard.log" in text
    assert "action" in text
    assert "detail" in text
    assert "pull_up_start" in text or "pull_up_ok" in text


def test_guard_idempotent_no_kill():
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "kill -9" not in text  # 程序最小化：守护不做强杀
    assert "detect_fail" in text


def test_guard_status_mode():
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "status)" in text
    assert "once" in text
