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


# ── R4/A3: 本地真实回归脚本静态断言 ──


def test_run_real_smoke_script_exists_and_syntax():
    """run_real_smoke.sh 存在、可执行、bash 语法正确（防回归）."""
    import subprocess
    from pathlib import Path as _Path

    script = _Path(__file__).resolve().parents[2] / "scripts" / "run_real_smoke.sh"
    assert script.exists()
    assert script.stat().st_mode & 0o111  # 可执行位
    proc = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    text = script.read_text(encoding="utf-8")
    # 关键要素：key 从 .env 读取（不上传）、冒烟 + 评测两段
    assert "DEEPSEEK_API_KEY" in text
    assert ".env" in text
    assert "run_eval.py" in text
    assert "real_llm_smoke" in text
