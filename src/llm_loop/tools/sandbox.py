"""bash 沙箱后端（P3-3，2026-08-15）.

`EXEC_SANDBOX` env：
- `bwrap`：用 bubblewrap 隔离 execute_command——只读系统目录（/usr /etc /lib /lib64 /bin /sbin）、
  /dev /proc 挂载、/tmp 临时文件系统、工作区可写绑定、独立 PID/UTS/IPC 命名空间；
  **bwrap 缺失时拒绝执行**（fail-closed：显式安全意图不静默降级，回执如实说明）。
- 空/其他：不启用（默认，零回归）。

bwrap 仅 Linux 提供（macOS 不提供）；"配置即意图"——显式开启而工具缺失 → 命令不执行。
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable

logger = logging.getLogger(__name__)

_BWRAP_RO_BINDS = ("/usr", "/etc", "/lib", "/lib64", "/bin", "/sbin")


def sandbox_mode() -> str:
    """当前沙箱模式（bwrap / none）."""
    return os.environ.get("EXEC_SANDBOX", "").strip().lower() or "none"


def bwrap_argv(command: str, workdir: str) -> list[str]:
    """构造 bwrap argv（shell=False 执行，避免 shell=True 引号地狱）."""
    argv = [
        "bwrap",
        "--unshare-pid",
        "--unshare-uts",
        "--unshare-ipc",
    ]
    for path in _BWRAP_RO_BINDS:
        argv += ["--ro-bind", path, path]
    argv += ["--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]
    argv += ["--bind", workdir, workdir, "--chdir", workdir]
    argv += ["/bin/sh", "-c", command]
    return argv


def sandbox_argv(command: str, workdir: str) -> tuple[list[str] | None, str]:
    """按 EXEC_SANDBOX 返回 (argv, note)。

    - 未启用 → (None, "")（调用方走既有 shell=True 路径，零回归）
    - bwrap 且可用 → (argv, "（已启用 bwrap 沙箱）")
    - bwrap 但不可用 → 抛 RuntimeError（fail-closed，调用方如实失败回执）
    """
    mode = sandbox_mode()
    if mode != "bwrap":
        return (None, "")
    if shutil.which("bwrap") is None:
        raise RuntimeError(
            "EXEC_SANDBOX=bwrap 已显式配置，但系统找不到 bwrap（bubblewrap）——"
            "fail-closed：命令未执行。请安装 bubblewrap（Linux: apt install bubblewrap）"
            "或设 EXEC_SANDBOX=none 关闭沙箱。"
        )
    return (bwrap_argv(command, workdir), "（已启用 bwrap 沙箱）")


# 便捷签名（测试/调用方断言用）
Builder = Callable[[str, str], list[str]]
