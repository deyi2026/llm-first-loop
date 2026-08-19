"""Managed mock harness 评测：自带 mock raw server 生命周期管理（修复孤儿进程缺陷）.

原 run_harness_mock.py 缺陷（2026-08-19 排查确认）：依赖外部手动启动 http.server 8765，
评测完不回收 → 每次评测后留孤儿进程（PPID=1，端口 8765 长期占用）。
本脚本：spawn raw_server → wait port ready → run harness → finally terminate（+ atexit 双保险），
评测正常/异常均回收子进程，无 8765 残留；不依赖外部手动启动 mock server。

2026-08-20 加固（孤儿复现 58309 复盘——前版 SIGTERM/SIGINT 下 finally/atexit 不执行）：
1. 信号处理：SIGTERM/SIGINT → 先回收 raw server → 再清理本进程组（harness 的
   multiprocessing workers 一并回收），最后退出——"任务中断"不再留孤儿。
2. 进程组隔离：raw server 用 start_new_session=True 独立会话启动，与 harness 组隔离，
   信号清理互不误伤；回收时 terminate 其整个进程组（防其间接子进程残留）。
3. 启动前孤儿清扫：端口被旧 raw_server.py 占用时（前次中断残留）默认 kill 后自启，
   --no-sweep 可禁用（复用外部服务场景）；检测失败 fail-open 转复用。
4. 可观测：每次启动/回收打印 pid 与端口状态，脚本退出后可用
   `lsof -tiTCP:8765 -sTCP:LISTEN` 复核无残留。

用法: python3 scripts/harness_mock/run_harness_mock_managed.py [--no-sweep]
"""
from __future__ import annotations  # 注解延迟求值（兼容 Python 3.9：`X | None` 不在定义时求值）

import atexit
from pathlib import Path
import os
import signal
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

PORT = 8765
RAW_SERVER = str(Path(__file__).resolve().parent / 'raw_server.py')

_server_proc = None
_own_session = False  # raw server 是否由本进程启动（决定回收责任）


# ── 端口/进程探测（macOS/Linux 兼容，探测失败 fail-open）──

def _listener_pids(port: int) -> list[int]:
    """返回监听指定端口的 pid 列表（lsof；失败返回 []）. """
    try:
        out = subprocess.run(
            ['lsof', '-tiTCP:%d' % port, '-sTCP:LISTEN'],
            capture_output=True, text=True, timeout=5,
        )
        return [int(p) for p in out.stdout.split() if p.strip().isdigit()]
    except Exception:  # noqa: BLE001 — 探测失败 fail-open
        return []


def _cmdline_has_raw_server(pid: int) -> bool:
    """判断 pid 是否 raw_server.py 进程. 多路探测（/proc → ps args），全失败 fail-open False."""
    # 方法1: /proc/<pid>/cmdline（Linux，完整 argv）
    try:
        with open(f'/proc/{pid}/cmdline', 'rb') as f:
            if b'raw_server.py' in f.read():
                return True
    except Exception:  # noqa: BLE001 — macOS 无 /proc 等
        pass
    # 方法2: ps -o args=（macOS/Linux 完整 argv；command= 会截断不用）
    try:
        out = subprocess.run(
            ['ps', '-p', str(pid), '-o', 'args='],
            capture_output=True, text=True, timeout=5,
        )
        if 'raw_server.py' in out.stdout:
            return True
    except Exception:  # noqa: BLE001 — ps 不可用等
        pass
    return False


# ── mock raw server 生命周期 ──

def _port_ready(port: int, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _kill_group(proc: subprocess.Popen) -> None:
    """SIGTERM 整个进程组（terminate 其间接子进程），超时 SIGKILL 兜底."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass  # 进程组已退出
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass


def _stop_raw_server() -> None:
    """回收 raw server 子进程（进程组 terminate → wait，超时 kill）. 幂等，仅回收自启进程."""
    global _server_proc, _own_session
    proc = _server_proc
    if proc is None or not _own_session:
        _server_proc = None
        return
    _server_proc = None
    _own_session = False
    if proc.poll() is None:
        _kill_group(proc)
        print(f"[managed] mock raw server 已回收 pid={proc.pid}", flush=True)
    else:
        print(f"[managed] mock raw server 已自行退出 pid={proc.pid} rc={proc.returncode}", flush=True)


def _sweep_stale_raw_server(sweep: bool) -> bool:
    """启动前清扫：端口被旧 raw_server.py 占用（前次中断残留）→ kill 后自启.

    Returns:
        True=可自启（端口已清理或本就空闲）；False=端口被非 raw_server 占用（复用，不自启）。
    """
    if not _port_ready(PORT, timeout=0.5):
        return True  # 端口空闲
    pids = _listener_pids(PORT)
    if not pids:
        print(f"[managed] 端口 {PORT} 有监听但无法识别，复用（不接管）", flush=True)
        return False
    if any(_cmdline_has_raw_server(p) for p in pids):
        if not sweep:
            print(f"[managed] 端口 {PORT} 被 raw_server.py 占用，--no-sweep 跳过清扫，复用", flush=True)
            return False
        for p in pids:
            if _cmdline_has_raw_server(p):
                try:
                    os.kill(p, signal.SIGTERM)
                    print(f"[managed] 清扫前次残留孤儿 raw_server pid={p}", flush=True)
                except (ProcessLookupError, PermissionError):
                    pass
        time.sleep(1.0)
        if _port_ready(PORT, timeout=1.0):
            print(f"[managed] 端口 {PORT} 清扫后仍被占用，复用（不接管）", flush=True)
            return False
        print(f"[managed] 端口 {PORT} 已清理，将自启", flush=True)
        return True
    print(f"[managed] 端口 {PORT} 被非 raw_server 服务占用，复用（不接管回收）", flush=True)
    return False


def _start_raw_server(sweep: bool = True):
    """启动本地 mock raw server（自管理）；端口被外部占用时复用不接管. 返回进程或 None."""
    global _server_proc, _own_session
    if not _sweep_stale_raw_server(sweep):
        return None  # 复用外部服务
    _server_proc = subprocess.Popen(
        [sys.executable, RAW_SERVER, str(PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,  # 独立进程组：与 harness 组隔离，回收互不误伤
    )
    _own_session = True
    atexit.register(_stop_raw_server)
    if not _port_ready(PORT):
        _stop_raw_server()
        raise RuntimeError(f"mock raw server 启动失败（端口 {PORT} 未就绪）")
    print(f"[managed] mock raw server 已启动 pid={_server_proc.pid}", flush=True)
    return _server_proc


# ── 信号处理：中断（kill/Ctrl+C）也回收，不留孤儿 ──

def _on_signal(signum, frame):
    """SIGTERM/SIGINT：回收 raw server → 清理本进程组（harness workers）→ 退出."""
    print(f"[managed] 收到信号 {signum}，回收子进程后退出", flush=True)
    _stop_raw_server()
    # 仅当本进程是进程组长时才 killpg（终端独立运行场景=组长，杀本作业组安全；
    # 被其他进程同组拉起时非组长——跳过，避免误杀同组父进程/兄弟进程）
    try:
        if os.getpgrp() == os.getpid():
            os.killpg(os.getpgid(0), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    sys.exit(128 + signum)


def _install_signal_handlers() -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):  # 非主线程/环境限制
            pass


# ── 主流程 ──

def main(argv: list[str] | None = None):
    argv = list(sys.argv[1:] if argv is None else argv)
    sweep = '--no-sweep' not in argv

    # 1. monkeypatch SWE_BENCH_URL_RAW → 本地 mock raw（必须在 import harness 模块前）
    import swebench.harness.constants as sc
    sc.SWE_BENCH_URL_RAW = f"http://127.0.0.1:{PORT}/"
    import swebench.harness.test_spec.python as py_mod
    py_mod.SWE_BENCH_URL_RAW = f"http://127.0.0.1:{PORT}/"

    _install_signal_handlers()

    # 2. 启动 mock raw server（自管理；先清扫前次残留）
    _start_raw_server(sweep=sweep)
    try:
        # 3. 跑标准 harness（参数与 run_harness_mock.py 一致）
        from swebench.harness.run_evaluation import main as harness_main, parse_args
        sys.argv = ['run_eval',
            '-d', 'data/swe_results/standard/pylint_dataset.json',
            '-s', 'test',
            '-p', 'data/swe_results/standard/pylint_preds.jsonl',
            '--max_workers', '4',
            '-id', 'pylint-standard-20260817',
            '--cache_level', 'base',
            '--report_dir', 'data/swe_results/standard/reports',
        ]
        args = parse_args()
        harness_main(**vars(args))
        return 0
    finally:
        _stop_raw_server()


if __name__ == '__main__':
    raise SystemExit(main())
