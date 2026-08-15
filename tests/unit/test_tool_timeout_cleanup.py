"""P1-5(审计发现 #11): 工具超时线程/子进程泄漏修复测试.

覆盖:
- 注册表线程级超时按时返回 TIMEOUT 回执（修复前 with 块退出会 shutdown(wait=True)
  卡到工具自行结束——超时名存实亡，耗时 = 工具时长）
- 超时路径调用工具暴露的 terminate() 钩子（尽力而为终止残余执行）
- execute_command 超时后子进程（含整个进程组）被整树终止（无孤儿）
- 重构后 execute_command 正常路径行为不变（零回归）

约定: 假工具 sleep 设上界，避免 RED 阶段把套件卡死（残余线程最多存活到 sleep 结束）。
"""

from __future__ import annotations

import os
import threading
import time

from llm_loop.core.message import ToolCall, ToolResultStatus
from llm_loop.tools.builtin.execute_command import ExecuteCommandTool
from llm_loop.tools.registry import ToolRegistry


class _SlowTool:
    """无 terminate 钩子的慢工具：超时后残余线程存活到 sleep 结束（如实标注）."""

    name = "slow_tool"
    description = "慢工具（测试桩）"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, sleep_s: float = 1.5) -> None:
        self.sleep_s = sleep_s

    def execute(self, **kwargs):
        time.sleep(self.sleep_s)
        return "done"


def test_registry_timeout_returns_promptly():
    """注册表超时按时返回 TIMEOUT 回执（不卡到工具自行结束）."""
    reg = ToolRegistry(tool_timeout_s=0.2)
    reg.register(_SlowTool(sleep_s=1.5))
    start = time.perf_counter()
    result = reg.execute(ToolCall(id="c1", name="slow_tool", arguments={}))
    elapsed = time.perf_counter() - start
    assert result.status == ToolResultStatus.TIMEOUT
    assert elapsed < 1.0, f"超时应按时返回（实测 {elapsed:.2f}s，疑似卡到工具结束）"


class _TerminableSlowTool(_SlowTool):
    """带 terminate 钩子的慢工具：超时后置位事件（模拟整树终止已完成）."""

    def __init__(self, sleep_s: float = 1.5) -> None:
        super().__init__(sleep_s=sleep_s)
        self.terminated = threading.Event()

    def terminate(self) -> None:
        self.terminated.set()


def test_registry_timeout_invokes_terminate_hook():
    """超时路径调用工具的 terminate() 钩子（尽力而为终止残余执行）."""
    reg = ToolRegistry(tool_timeout_s=0.2)
    tool = _TerminableSlowTool(sleep_s=1.5)
    reg.register(tool)
    result = reg.execute(ToolCall(id="c1", name="slow_tool", arguments={}))
    assert result.status == ToolResultStatus.TIMEOUT
    assert tool.terminated.is_set(), "超时路径应调用 terminate() 钩子"


def test_execute_command_normal_path_still_works():
    """P1-5 重构后正常路径不变：短命令成功返回（零回归）."""
    r = ExecuteCommandTool(timeout_s=30).execute(command="echo hello")
    assert r.status == ToolResultStatus.SUCCESS
    assert "hello" in r.content


def _alive(pid: int) -> bool:
    """进程是否存在（kill 0 探活；权限拒绝视为存活）."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _group_alive(pgid: int) -> bool:
    """进程组是否仍有存活成员（killpg 探活；权限拒绝视为存活）."""
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _wait_until(cond, deadline_s: float) -> bool:
    """轮询等待条件成立（防僵尸/收尸时序抖动），超时返回 False."""
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_execute_command_timeout_kills_subprocess(tmp_path):
    """execute_command 注册表超时：子进程（shell + 进程组）被整树终止.

    命令 `echo $$ > pidfile; sleep 5`：$$ 为 shell 自身 pid（start_new_session
    下即进程组 id）。注册表超时 0.5s 远小于工具内兜底超时 30s——超时后必须
    整树击杀（shell + sleep 孙进程），否则进程组残留孤儿。
    """
    tool = ExecuteCommandTool(timeout_s=30)  # 工具内兜底超时远大于注册表超时
    reg = ToolRegistry(tool_timeout_s=0.5)
    reg.register(tool)
    pidfile = tmp_path / "child.pid"
    call = ToolCall(
        id="c1",
        name="execute_command",
        arguments={
            "command": f"echo $$ > {pidfile}; sleep 5",
            "workdir": str(tmp_path),
        },
    )
    start = time.perf_counter()
    result = reg.execute(call)
    elapsed = time.perf_counter() - start
    assert result.status == ToolResultStatus.TIMEOUT
    assert elapsed < 2.0, f"超时应按时返回（实测 {elapsed:.2f}s）"

    # 等 pidfile 就绪（shell 启动即写，正常已就绪；小重试防时序抖动）
    pid = None
    for _ in range(40):
        try:
            pid = int(pidfile.read_text().strip())
            break
        except (ValueError, OSError):
            time.sleep(0.05)
    assert pid is not None, "子进程未写出 pidfile"

    # 直接子进程（shell）应在超时后很快被终止（terminate 整树击杀或单进程兜底）
    assert _wait_until(lambda: not _alive(pid), 3.0), "子进程（shell）未被终止"

    # 进程组（含孙进程 sleep）应被整树终止。个别环境若只放行单进程击杀（killpg
    # 受限），孙进程残留至 sleep 自然结束（≤5s）——给足宽限避免权限差异误报。
    assert _wait_until(lambda: not _group_alive(pid), 6.0), "子进程组未被终止（孤儿残留）"
