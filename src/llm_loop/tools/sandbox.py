"""bash 沙箱后端（P3-3，2026-08-15；docker 后端 2026-09-12）.

`EXEC_SANDBOX` env：
- `bwrap`：用 bubblewrap 隔离 execute_command——只读系统目录（/usr /etc /lib /lib64 /bin /sbin）、
  /dev /proc 挂载、/tmp 临时文件系统、工作区可写绑定、独立 PID/UTS/IPC 命名空间；
  **bwrap 缺失时拒绝执行**（fail-closed：显式安全意图不静默降级，回执如实说明）。
  注意：bwrap 配置**不隔离网络**（命名空间未含 network）。
- `docker`：容器后端（macOS/Linux，需本机 Docker）——`--network=none` 断网、
  `--read-only` 只读 rootfs、工作区 bind-mount 可写、`--user uid:gid` 保持宿主文件属主
  （避免容器内 root 在宿主留下 root 属主文件）、`--cap-drop ALL`、`--pids-limit`。
  镜像由 `EXEC_SANDBOX_IMAGE` 配置（默认 python:3.13-slim）。
  **CLI 缺失时拒绝执行**（fail-closed 同上；daemon 未启动 → 命令如实失败，不降级）。
- 空/其他：不启用（默认，零回归）。

bwrap 仅 Linux 提供；docker 后端是 macOS 上唯一的容器隔离路径。
"配置即意图"——显式开启而后端缺失 → 命令不执行。

运行条件与边界声明见 docs/operations/EXECUTION-ISOLATION.md。
"""

from __future__ import annotations

import logging
import os
import shutil
from collections.abc import Callable

logger = logging.getLogger(__name__)

_BWRAP_RO_BINDS = ("/usr", "/etc", "/lib", "/lib64", "/bin", "/sbin")
_DEFAULT_IMAGE = "python:3.13-slim"


def sandbox_mode() -> str:
    """当前沙箱模式（bwrap / docker / none）."""
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


def docker_argv(command: str, workdir: str) -> list[str]:
    """构造 docker run argv（容器后端）.

    - --network=none: 断网（严于 bwrap）
    - --read-only + 工作区 bind rw: rootfs 只读, 仅工作区可写
    - --user uid:gid: 容器进程与宿主当前用户同 uid, bind-mount 内新建文件不变成 root 属主
    - --cap-drop ALL / --pids-limit: 收紧能力与进程数
    """
    image = os.environ.get("EXEC_SANDBOX_IMAGE", "").strip() or _DEFAULT_IMAGE
    uid, gid = os.getuid(), os.getgid()
    return [
        "docker", "run", "--rm",
        "--network=none",
        "--read-only",
        "--cap-drop", "ALL",
        "--pids-limit", "256",
        "--tmpfs", "/tmp:rw,size=64m",
        "--user", f"{uid}:{gid}",
        "--volume", f"{workdir}:{workdir}:rw",
        "--workdir", workdir,
        image,
        "sh", "-c", command,
    ]


def sandbox_argv(command: str, workdir: str) -> tuple[list[str] | None, str]:
    """按 EXEC_SANDBOX 返回 (argv, note)。

    - 未启用 → (None, "")（调用方走既有 shell=True 路径，零回归）
    - bwrap/docker 且可用 → (argv, "（已启用 bwrap/docker 沙箱）")
    - 显式开启但后端不可用 → 抛 RuntimeError（fail-closed，调用方如实失败回执）
    """
    mode = sandbox_mode()
    workdir = os.path.abspath(workdir)
    if mode == "bwrap":
        if shutil.which("bwrap") is None:
            raise RuntimeError(
                "EXEC_SANDBOX=bwrap 已显式配置，但系统找不到 bwrap（bubblewrap）——"
                "fail-closed：命令未执行。请安装 bubblewrap（Linux: apt install bubblewrap）"
                "或改用 EXEC_SANDBOX=docker（macOS 可用）或 EXEC_SANDBOX=none。"
            )
        return (bwrap_argv(command, workdir), "（已启用 bwrap 沙箱）")
    if mode == "docker":
        if shutil.which("docker") is None:
            raise RuntimeError(
                "EXEC_SANDBOX=docker 已显式配置，但系统找不到 docker CLI——"
                "fail-closed：命令未执行。请安装/启动 Docker Desktop "
                f"（镜像可用 EXEC_SANDBOX_IMAGE 指定，默认 {_DEFAULT_IMAGE}）"
                "或设 EXEC_SANDBOX=none。"
            )
        return (docker_argv(command, workdir), "（已启用 docker 沙箱：断网/只读 rootfs/工作区可写）")
    return (None, "")


# 便捷签名（测试/调用方断言用）
Builder = Callable[[str, str], list[str]]
