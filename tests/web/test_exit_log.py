"""P1-3-R1: web 退出信号记录测试.

验证 `_install_exit_signal_log` 安装的信号处理器在 SIGTERM/SIGINT 到达时
追加写 `data/web_exit.log`（时刻/pid/信号名），fail-open 不阻塞退出行为。
"""

import os
from pathlib import Path

from llm_loop.web import _install_exit_signal_log


def _invoke_handler(signum: int) -> list[str]:
    """触发信号处理器并收集写盘内容（重定向 DATA_DIR 防污染真实日志）."""
    import tempfile

    tmp = tempfile.mkdtemp(prefix="web_exit_test_")
    os.environ["DATA_DIR"] = tmp

    _install_exit_signal_log()

    # 从信号表中取回处理器并调用（不等真实信号，隔离测试）
    import signal

    handler = signal.getsignal(signum)
    handler(signum, None)
    handler(signum, None)  # 幂等验证：两次调用两条记录

    log_path = Path(tmp) / "web_exit.log"
    if not log_path.exists():
        return []
    return log_path.read_text(encoding="utf-8").strip().splitlines()


def test_web_exit_log_on_sigterm():
    lines = _invoke_handler(15)
    assert len(lines) == 2
    assert "收到信号 15 (SIGTERM)" in lines[0]
    assert f"pid={os.getpid()}" in lines[0]
    assert "收到信号 15 (SIGTERM)" in lines[1]


def test_web_exit_log_on_sigint():
    lines = _invoke_handler(2)
    assert len(lines) == 2
    assert "收到信号 2 (SIGINT)" in lines[0]


def test_web_exit_log_fail_open(tmp_path, monkeypatch):
    """写路径不可写（open 抛 OSError）→ 信号处理器不抛异常."""
    import tempfile

    tmp = tempfile.mkdtemp(prefix="web_exit_test_")
    os.environ["DATA_DIR"] = tmp
    _install_exit_signal_log()

    import signal

    handler = signal.getsignal(signal.SIGTERM)

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", _boom)
    handler(15, None)  # 不抛异常即通过


def test_web_signal_handler_does_not_block():
    """信号处理器仅记录不阻塞（调用后无异常、进程未退出）."""
    lines = _invoke_handler(15)
    assert lines  # 已记录
