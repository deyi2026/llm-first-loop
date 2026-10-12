"""run_harness_mock_managed 生命周期测试：孤儿清扫 + 信号中断回收."""
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_harness_mock_managed as managed


def port_free() -> bool:
    try:
        with socket.create_connection(('127.0.0.1', managed.PORT), timeout=0.5):
            return False
    except OSError:
        return True


def test_normal_start_stop():
    assert port_free(), "前置: 8765 应空闲"
    p = managed._start_raw_server()
    assert p is not None, "应自启 raw server"
    time.sleep(0.5)
    assert not port_free(), "启动后端口应被监听"
    managed._stop_raw_server()
    time.sleep(0.5)
    assert port_free(), "停止后端口应释放"
    print("TEST1 正常启动/停止回收: PASS")


def test_stale_orphan_sweep():
    # 模拟前次中断残留：手动起一个无人管理的 raw server
    orphan = subprocess.Popen(
        [sys.executable, managed.RAW_SERVER, str(managed.PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)
    assert not port_free(), "孤儿 server 应监听"
    # monkeypatch 检测命中（真实环境 ps/proc 可识别 raw_server.py；沙箱禁 ps 故模拟）
    _orig = managed._cmdline_has_raw_server
    managed._cmdline_has_raw_server = lambda pid: True
    ok = managed._sweep_stale_raw_server(sweep=True)
    time.sleep(0.5)
    assert ok, "清扫应返回可自启"
    assert port_free(), "清扫后端口应释放"
    assert orphan.poll() is not None, "孤儿进程应被终止"
    print("TEST2 启动前孤儿清扫(检测命中): PASS")


def test_sweep_reuse_when_detection_unavailable():
    """检测不可用（ps 被禁等）→ 不误杀，转复用."""
    orphan = subprocess.Popen(
        [sys.executable, managed.RAW_SERVER, str(managed.PORT)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)
    managed._cmdline_has_raw_server = lambda pid: False
    ok = managed._sweep_stale_raw_server(sweep=True)
    time.sleep(0.3)
    assert ok is False, "检测不到时应返回复用（不误杀）"
    assert orphan.poll() is None, "孤儿不应被误杀"
    print("TEST2b 检测不可用→复用不误杀: PASS")
    # 清理本测试的孤儿
    orphan.terminate()
    orphan.wait(timeout=10)
    time.sleep(0.3)
    assert port_free(), "测试孤儿已清理"


def test_signal_interrupt_cleanup():
    # 子进程: 装信号处理器 + 自启 server 后挂起；父进程 SIGTERM → 验证子进程退出且端口释放
    # 子进程注入脚本目录（动态构造，避免硬编码机器绝对路径——git 安全扫描拒绝 /Users/*/）
    _scripts_dir = str(Path(__file__).resolve().parent)
    child_code = f'''
import sys, time
sys.path.insert(0, r'{_scripts_dir}')
import run_harness_mock_managed as managed
managed._install_signal_handlers()
managed._start_raw_server(sweep=True)
print("READY", flush=True)
time.sleep(120)
'''
    child = subprocess.Popen(
        [sys.executable, '-c', child_code],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    # 等 READY 且端口就绪（子进程会先打印启动日志，循环读到 READY）
    line = ""
    deadline = time.time() + 15
    while time.time() < deadline:
        line = child.stdout.readline().strip()
        if line == "READY":
            break
    assert line == "READY", f"子进程未就绪: {line!r}"
    time.sleep(0.5)
    assert not port_free(), "子进程应已监听 8765"
    child.terminate()  # SIGTERM —— 旧版在此会留孤儿
    rc = child.wait(timeout=15)
    time.sleep(0.5)
    assert rc == 128 + 15, f"子进程应以 143 退出, got {rc}"
    assert port_free(), "中断后端口应释放（无孤儿）"
    print("TEST3 SIGTERM 中断回收: PASS (rc=143, 端口已释放)")


if __name__ == '__main__':
    test_normal_start_stop()
    test_stale_orphan_sweep()
    test_sweep_reuse_when_detection_unavailable()
    test_signal_interrupt_cleanup()
    print("\n全部通过 ✅")
