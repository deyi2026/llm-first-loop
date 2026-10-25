"""bash 沙箱后端（P3-3，2026-08-15；docker 后端 2026-09-12；auto/sandbox-exec 2026-10-25，P2-1）.

`EXEC_SANDBOX` env：
- `auto`（config 默认值）：首次执行时按平台顺序解析可用后端并进程内缓存，解析结果写一次日志
  （落到 none → warning，明确列出原因，绝不静默）：
  - darwin：`sandbox-exec` → `docker`（P1-1，Rule28 修复轮：docker 后端跑 Linux 镜像，
    宿主 .venv 的 Mach-O 解释器在容器内 exec-format 失败，且首个用户会被 image pull
    卡住，故 macOS 原生 sandbox-exec 优先；auto 落到 docker-on-darwin 时打一条
    warning，提示显式设 EXEC_SANDBOX=none/docker）；
  - 其余平台：`bwrap`（`shutil.which("bwrap")` 命中）→ `docker`（CLI 存在且
    `docker info` 2s 内成功，daemon 在跑，结果进程内缓存）→ `sandbox-exec`（仅
    darwin，其余平台恒不可用）→ 都不可用 → none（`EXEC_SANDBOX_STRICT=1` 时
    fail-closed，见下）。
- `bwrap`：用 bubblewrap 隔离 execute_command——只读系统目录（/usr /etc /lib /lib64 /bin /sbin）、
  /dev /proc 挂载、/tmp 临时文件系统、工作区可写绑定、独立 PID/UTS/IPC 命名空间；
  **bwrap 缺失时拒绝执行**（fail-closed：显式安全意图不静默降级，回执如实说明）。
  注意：bwrap 配置**不隔离网络**（命名空间未含 network）。
- `docker`：容器后端（macOS/Linux，需本机 Docker）——`--network=none` 断网、
  `--read-only` 只读 rootfs、工作区 bind-mount 可写、`--user uid:gid` 保持宿主文件属主
  （避免容器内 root 在宿主留下 root 属主文件）、`--cap-drop ALL`、`--pids-limit`。
  镜像由 `EXEC_SANDBOX_IMAGE` 配置（默认 python:3.13-slim）。
  **CLI 缺失时拒绝执行**（fail-closed 同上；daemon 未启动 → 命令如实失败，不降级）。
- `sandbox-exec`：macOS 原生 Seatbelt 后端——profile 为
  `(version 1)(allow default)(deny file-write*)(allow file-write* (subpath <root>))`，
  **只约束写域**：可写根 = 工作区 + /tmp + /private/tmp + /dev + ~/.cache +
  ~/Library/Caches + ~/.npm + `EXEC_SANDBOX_MACOS_WRITABLE`（os.pathsep 分隔的追加项）；
  路径做 S 表达式转义（双引号/反斜杠）防策略注入。**不隔离网络、不限制读**。
  非 darwin 或 sandbox-exec 不可用 → fail-closed 拒绝执行。
- `none`：不启用（零回归；auto 解析到 none 且非 strict 时同此，但必先写一次 warning）。

`EXEC_SANDBOX_STRICT=1`：auto 解析到 none → RuntimeError（fail-closed，回执如实失败）；
默认不 strict（docker daemon 未启动等场景下常规命令仍可用，落到次优后端或 none+告警）。

"配置即意图"——bwrap/docker/sandbox-exec 显式开启而后端缺失 → 命令不执行。

运行条件与边界声明见 docs/EXECUTION-ISOLATION.md。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)

_BWRAP_RO_BINDS = ("/usr", "/etc", "/lib", "/lib64", "/bin", "/sbin")
_DEFAULT_IMAGE = "python:3.13-slim"
_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_DOCKER_INFO_TIMEOUT_S = 2.0

# S2-6（安全建议书 2026-10-25）：note 文案必须与实际后端能力一一对应，不得夸大隔离范围。
_BWRAP_NOTE = "（已启用 bwrap 沙箱：只读系统目录/工作区可写/未隔离网络）"
_DOCKER_NOTE = "（已启用 docker 沙箱：断网/只读 rootfs/工作区可写）"
_SANDBOX_EXEC_NOTE = "（已启用 macOS sandbox-exec 沙箱：仅允许写工作区与缓存目录/未隔离网络）"

# auto 解析进程内缓存（backend, reasons）；docker daemon 探测结果独立缓存。
_auto_cache: tuple[str, list[str]] | None = None
_auto_logged = False
_docker_daemon_cache: bool | None = None
_docker_probe_detail = "未探测"
_sandbox_exec_detail = "未探测"


def reset_auto_cache() -> None:
    """清空 auto 解析与 docker 探测缓存（测试钩子；生产进程只解析一次）。"""
    global _auto_cache, _auto_logged, _docker_daemon_cache
    global _docker_probe_detail, _sandbox_exec_detail
    _auto_cache = None
    _auto_logged = False
    _docker_daemon_cache = None
    _docker_probe_detail = "未探测"
    _sandbox_exec_detail = "未探测"


def _strict_enabled() -> bool:
    return os.environ.get("EXEC_SANDBOX_STRICT", "").strip().lower() in {"1", "true", "yes", "on"}


def _probe_bwrap() -> bool:
    return shutil.which("bwrap") is not None


def _probe_docker() -> bool:
    """docker CLI 存在且 `docker info` 成功（2s 超时）；结果进程内缓存。"""
    global _docker_daemon_cache, _docker_probe_detail
    if _docker_daemon_cache is not None:
        return _docker_daemon_cache
    if shutil.which("docker") is None:
        _docker_probe_detail = "docker CLI 不在 PATH"
        _docker_daemon_cache = False
        return False
    try:
        proc = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=_DOCKER_INFO_TIMEOUT_S
        )
    except subprocess.TimeoutExpired:
        _docker_probe_detail = f"docker info 探测超时（>{_DOCKER_INFO_TIMEOUT_S:.0f}s）"
        _docker_daemon_cache = False
        return False
    except (OSError, subprocess.SubprocessError) as exc:
        _docker_probe_detail = f"docker info 执行失败（{type(exc).__name__}）"
        _docker_daemon_cache = False
        return False
    _docker_daemon_cache = proc.returncode == 0
    _docker_probe_detail = (
        "daemon 可用（docker info 成功）"
        if _docker_daemon_cache
        else "daemon 未运行（docker info 非零退出）"
    )
    return _docker_daemon_cache


def _probe_sandbox_exec() -> bool:
    global _sandbox_exec_detail
    if sys.platform != "darwin":
        _sandbox_exec_detail = f"当前平台 {sys.platform!r} 非 darwin"
        return False
    if not (os.path.isfile(_SANDBOX_EXEC) and os.access(_SANDBOX_EXEC, os.X_OK)):
        _sandbox_exec_detail = f"{_SANDBOX_EXEC} 不存在或不可执行"
        return False
    _sandbox_exec_detail = f"{_SANDBOX_EXEC} 可执行"
    return True


def resolve_auto_backend() -> tuple[str, list[str]]:
    """auto 解析（进程内缓存，结果日志写一次）.

    - darwin：sandbox-exec → docker → none（P1-1：docker 跑 Linux 镜像，
      宿主 .venv（Mach-O）不兼容，sandbox-exec 优先）；
    - 其余平台：bwrap → docker → sandbox-exec → none（维持既有顺序不变）。
    """
    global _auto_cache, _auto_logged
    if _auto_cache is None:
        if sys.platform == "darwin":
            # P1-1（Rule28 修复轮）：darwin 上 sandbox-exec 优先于 docker——
            # docker-on-darwin 跑 Linux 镜像（--network=none 的 python:3.13-slim），
            # 宿主 .venv（Mach-O）进容器 exec-format 失败，首用户还会被 image pull 卡住。
            if _probe_sandbox_exec():
                _auto_cache = ("sandbox-exec", [_sandbox_exec_detail])
            elif _probe_docker():
                _auto_cache = ("docker", [_docker_probe_detail])
                logger.warning(
                    "EXEC_SANDBOX=auto 在 darwin 上解析到 docker："
                    "docker on darwin runs linux images; host venv incompatible; "
                    "set EXEC_SANDBOX=none/docker consciously"
                )
            else:
                _auto_cache = (
                    "none",
                    [
                        f"sandbox-exec 不可用（{_sandbox_exec_detail}）",
                        f"docker 不可用（{_docker_probe_detail}）",
                        "bwrap 不参与 darwin auto 探测（darwin 顺序：sandbox-exec → docker）",
                    ],
                )
        elif _probe_bwrap():
            _auto_cache = ("bwrap", ["bwrap 已安装"])
        elif _probe_docker():
            _auto_cache = ("docker", [_docker_probe_detail])
        elif _probe_sandbox_exec():
            _auto_cache = ("sandbox-exec", [_sandbox_exec_detail])
        else:
            _auto_cache = (
                "none",
                [
                    "bwrap 未安装（PATH 中无 bubblewrap）",
                    f"docker 不可用（{_docker_probe_detail}）",
                    f"sandbox-exec 不可用（{_sandbox_exec_detail}）",
                ],
            )
        backend, why = _auto_cache
        if not _auto_logged:
            _auto_logged = True
            if backend == "none":
                logger.warning(
                    "未启用沙箱：%s（EXEC_SANDBOX=auto 未解析到任何可用后端，"
                    "仅 CatastrophicGuard deny-list 兜底）",
                    "；".join(why),
                )
            else:
                logger.info("EXEC_SANDBOX=auto 已解析沙箱后端 %s（%s）", backend, why[0])
    return _auto_cache


def sandbox_mode(raw: str = "none") -> str:
    """Normalize a sandbox mode (auto / bwrap / docker / sandbox-exec / none).

    非法值回落 none 并 warning（保持既有"回落"风格，但不再静默）。
    """
    mode = str(raw or "none").strip().lower()
    if mode in {"auto", "bwrap", "docker", "sandbox-exec", "none"}:
        return mode
    logger.warning(
        "EXEC_SANDBOX 非法值 %r → 回落 none（合法：auto/bwrap/docker/sandbox-exec/none）",
        raw,
    )
    return "none"


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


def docker_argv(command: str, workdir: str, *, image: str = _DEFAULT_IMAGE) -> list[str]:
    """构造 docker run argv（容器后端）.

    - --network=none: 断网（严于 bwrap）
    - --read-only + 工作区 bind rw: rootfs 只读, 仅工作区可写
    - --user uid:gid: 容器进程与宿主当前用户同 uid, bind-mount 内新建文件不变成 root 属主
    - --cap-drop ALL / --pids-limit: 收紧能力与进程数
    """
    image = str(image or _DEFAULT_IMAGE).strip() or _DEFAULT_IMAGE
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


def _sbx_escape(path: str) -> str:
    """S 表达式字符串字面量转义（反斜杠、双引号），防路径注入破坏策略。"""
    return path.replace("\\", "\\\\").replace('"', '\\"')


def macos_writable_roots(workdir: str, *, extra: Iterable[str] = ()) -> list[str]:
    """sandbox-exec profile 可写根：工作区 + 系统临时/设备 + 用户缓存 + env 追加项.

    env 追加项：`EXEC_SANDBOX_MACOS_WRITABLE`（os.pathsep 分隔）。
    """
    home = os.path.expanduser("~")
    candidates: list[str] = [
        workdir,
        "/tmp",
        "/private/tmp",
        "/dev",
        os.path.join(home, ".cache"),
        os.path.join(home, "Library", "Caches"),
        os.path.join(home, ".npm"),
    ]
    candidates += [
        p for p in os.environ.get("EXEC_SANDBOX_MACOS_WRITABLE", "").split(os.pathsep) if p
    ]
    candidates += [str(p) for p in extra if p]
    roots: list[str] = []
    for cand in candidates:
        root = os.path.abspath(os.path.expanduser(cand))
        if root not in roots:
            roots.append(root)
    return roots


def sandbox_exec_profile(writable_roots: Iterable[str]) -> str:
    """生成 Seatbelt profile：deny 全部写，再逐 subpath 放行（父代理 2026-10-25 实测形态）."""
    allows = "".join(
        f'(allow file-write* (subpath "{_sbx_escape(os.fspath(root))}"))'
        for root in writable_roots
    )
    return f"(version 1)(allow default)(deny file-write*){allows}"


def sandbox_exec_argv(
    command: str, workdir: str, *, writable_roots: Iterable[str] = ()
) -> list[str]:
    """构造 sandbox-exec argv（仅 darwin；调用方 Popen shell=False 执行）."""
    profile = sandbox_exec_profile(macos_writable_roots(workdir, extra=writable_roots))
    return [_SANDBOX_EXEC, "-p", profile, "/bin/bash", "-lc", command]


def sandbox_argv(
    command: str,
    workdir: str,
    *,
    mode: str = "none",
    image: str = _DEFAULT_IMAGE,
) -> tuple[list[str] | None, str]:
    """按 EXEC_SANDBOX 返回 (argv, note)。

    - none → (None, "")（调用方走既有 shell=True 路径，零回归；note 不加任何"已隔离"措辞）
    - auto → 解析到具体后端后按该后端执行；解析到 none：非 strict 同 none（已先行写
      warning），EXEC_SANDBOX_STRICT=1 → RuntimeError（fail-closed，回执如实失败）
    - bwrap/docker/sandbox-exec 且可用 → (argv, note)（note 文案与实际后端一一对应，S2-6）
    - 显式开启但后端不可用 → 抛 RuntimeError（fail-closed，调用方如实失败回执）
    """
    mode = sandbox_mode(mode)
    workdir = os.path.abspath(workdir)
    if mode == "auto":
        backend, reasons = resolve_auto_backend()
        if backend == "none":
            if _strict_enabled():
                raise RuntimeError(
                    "EXEC_SANDBOX=auto 且 EXEC_SANDBOX_STRICT=1：未解析到任何沙箱后端——"
                    f"fail-closed：命令未执行。原因：{'；'.join(reasons)}。"
                    "请安装可用后端（Linux: bubblewrap；任意平台: 启动 docker daemon；"
                    "macOS: /usr/bin/sandbox-exec），或显式设 EXEC_SANDBOX=none。"
                )
            return (None, "")
        mode = backend
    if mode == "bwrap":
        if shutil.which("bwrap") is None:
            raise RuntimeError(
                "EXEC_SANDBOX=bwrap 已显式配置，但系统找不到 bwrap（bubblewrap）——"
                "fail-closed：命令未执行。请安装 bubblewrap（Linux: apt install bubblewrap）"
                "或改用 EXEC_SANDBOX=docker（macOS 可用）或 EXEC_SANDBOX=none。"
            )
        return (bwrap_argv(command, workdir), _BWRAP_NOTE)
    if mode == "docker":
        if shutil.which("docker") is None:
            raise RuntimeError(
                "EXEC_SANDBOX=docker 已显式配置，但系统找不到 docker CLI——"
                "fail-closed：命令未执行。请安装/启动 Docker Desktop "
                f"（镜像可用 EXEC_SANDBOX_IMAGE 指定，默认 {_DEFAULT_IMAGE}）"
                "或设 EXEC_SANDBOX=none。"
            )
        return (docker_argv(command, workdir, image=image), _DOCKER_NOTE)
    if mode == "sandbox-exec":
        if not _probe_sandbox_exec():
            raise RuntimeError(
                "EXEC_SANDBOX=sandbox-exec 已显式配置，但当前不可用"
                f"（{_sandbox_exec_detail}）——fail-closed：命令未执行。"
                "可改用 EXEC_SANDBOX=auto 自动解析或 EXEC_SANDBOX=none。"
            )
        return (sandbox_exec_argv(command, workdir), _SANDBOX_EXEC_NOTE)
    return (None, "")


# 便捷签名（测试/调用方断言用）
Builder = Callable[[str, str], list[str]]
