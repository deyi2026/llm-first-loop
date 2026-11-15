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
  可用性按**实跑套用**判定（2026-11-09）：二进制存在不够，进程已被外层沙箱包裹时
  内层 `sandbox_apply` 会被拒（EPERM，每条命令都以退出码 71 失败）。
  非 darwin、二进制缺失或套用被拒 → 视为不可用；auto 落到 none 时 note 如实说明
  "未套内层沙箱、写入边界仅由外层决定"，不宣称隔离。显式 sandbox-exec → fail-closed。
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
import stat
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence

logger = logging.getLogger(__name__)

_BWRAP_RO_BINDS = ("/usr", "/etc", "/lib", "/lib64", "/bin", "/sbin")
_DEFAULT_IMAGE = "python:3.13-slim"
_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_DOCKER_INFO_TIMEOUT_S = 2.0

# S2-6（安全建议书 2026-10-25）：note 文案必须与实际后端能力一一对应，不得夸大隔离范围。
_BWRAP_NOTE = "（已启用 bwrap 沙箱：只读系统目录/工作区可写/未隔离网络）"
_DOCKER_NOTE = "（已启用 docker 沙箱：断网/只读 rootfs/工作区可写）"
_AUDIT_PROTECTED_NOTE = "（受管审计目录写保护已启用：普通工作区仍可写）"
_SANDBOX_EXEC_NOTE = (
    "（已启用 macOS sandbox-exec 沙箱：仅允许写工作区与缓存目录/未隔离网络；"
    "已知降级：ps 为 setuid 在沙箱内 exec 即拒(EPERM)、launchctl list 空输出——"
    "进程/服务信息改用 lsof、sysctl、launchctl print）"
)

# auto 解析进程内缓存（backend, reasons）；docker daemon 探测结果独立缓存。
_auto_cache: tuple[str, list[str]] | None = None
_auto_logged = False
_docker_daemon_cache: bool | None = None
_docker_probe_detail = "未探测"
_sandbox_exec_detail = "未探测"
# sandbox-exec 实跑探测缓存：(可用, 说明, 嵌套说明)；仅"套用被拒"时第三项非空。
_sandbox_exec_apply_cache: tuple[bool, str, str] | None = None


def reset_auto_cache() -> None:
    """清空 auto 解析与 docker 探测缓存（测试钩子；生产进程只解析一次）。"""
    global _auto_cache, _auto_logged, _docker_daemon_cache
    global _docker_probe_detail, _sandbox_exec_detail, _sandbox_exec_apply_cache
    _auto_cache = None
    _auto_logged = False
    _docker_daemon_cache = None
    _docker_probe_detail = "未探测"
    _sandbox_exec_detail = "未探测"
    _sandbox_exec_apply_cache = None


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


def _sandbox_exec_probe_argv() -> list[str]:
    """实跑探测命令：用宿主上确定存在的可执行体套一次最宽松 profile。

    历史坑：曾以 `/bin/true` 探测，而本机（macOS 15）只有 `/usr/bin/true`——探测自身
    execvp 失败同样返回退出码 71，会被误读成"外层沙箱拒绝套用"。这里优先
    `/usr/bin/true`，缺失时回落到当前解释器，保证探测失败只可能来自"套用"这一步。
    """
    if os.path.isfile("/usr/bin/true"):
        return [_SANDBOX_EXEC, "-p", "(version 1)(allow default)", "/usr/bin/true"]
    return [_SANDBOX_EXEC, "-p", "(version 1)(allow default)", sys.executable, "-c", "pass"]


def _sandbox_exec_applicable() -> tuple[bool, str, str]:
    """实跑探测 sandbox-exec 能否真的套用 profile（进程内缓存）。

    仅探二进制存在不足以判定可用：进程已被外层沙箱包裹时，内层 sandbox-exec 会在
    sandbox_apply 阶段被拒（Operation not permitted），表现为**每条命令**都以退出码
    71 失败——与 profile 内容无关。这里套一条最宽松的 profile 实跑一次，按真实结果
    判定；只有拿到 `sandbox_apply` 拒绝签名才归因为"不能再套内层沙箱"，其余失败
    （探测体不存在、exec 被拒等）只如实记录，不冒充嵌套。
    """
    global _sandbox_exec_apply_cache
    if _sandbox_exec_apply_cache is not None:
        return _sandbox_exec_apply_cache
    argv = _sandbox_exec_probe_argv()
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=5.0, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _sandbox_exec_apply_cache = (
            False,
            f"{_SANDBOX_EXEC} 探测无法执行（{type(exc).__name__}: {exc}）",
            "",
        )
        return _sandbox_exec_apply_cache
    stderr = (proc.stderr or "").strip()
    if proc.returncode == 0:
        _sandbox_exec_apply_cache = (
            True,
            f"{_SANDBOX_EXEC} 可套用 profile（实跑探测通过）",
            "",
        )
        return _sandbox_exec_apply_cache
    first_line = stderr.splitlines()[0] if stderr else f"退出码 {proc.returncode}"
    if "sandbox_apply" in stderr:
        detail = f"{_SANDBOX_EXEC} 存在但 profile 套用被拒（{first_line}）"
        nested_note = (
            "（sandbox-exec 套用被拒：本进程不能再套内层沙箱；"
            "命令未套内层沙箱执行，写入边界仅由外层决定）"
        )
    else:
        detail = f"{_SANDBOX_EXEC} 探测失败（{first_line}）"
        nested_note = ""
    _sandbox_exec_apply_cache = (False, detail, nested_note)
    return _sandbox_exec_apply_cache


def _probe_sandbox_exec() -> bool:
    """sandbox-exec 是否可用（macOS + 二进制存在 + profile 实跑套用通过）。"""
    global _sandbox_exec_detail
    if sys.platform != "darwin":
        _sandbox_exec_detail = f"当前平台 {sys.platform!r} 非 darwin"
        return False
    if not (os.path.isfile(_SANDBOX_EXEC) and os.access(_SANDBOX_EXEC, os.X_OK)):
        _sandbox_exec_detail = f"{_SANDBOX_EXEC} 不存在或不可执行"
        return False
    applicable, detail, _nested = _sandbox_exec_applicable()
    _sandbox_exec_detail = detail
    return applicable


def sandbox_exec_available() -> bool:
    """sandbox-exec 可用性公开探针（EVO-20261115-488367d4 P0-1）.

    host-grant 前置检查用：macOS 上 grant 消费走 sandbox-exec 可写根追加，
    后端不可用时提前拒绝，不浪费人工审批（fail-closed 语义与 bwrap 预检一致）。
    """
    return _probe_sandbox_exec()


def _sandbox_exec_nested_note() -> str:
    """auto 因套用被拒降级 none 时的如实 note；未探测/非该形态返回空串。"""
    cache = _sandbox_exec_apply_cache
    if cache is not None and not cache[0]:
        return cache[2]
    return ""


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
                why_none = [
                    f"sandbox-exec 不可用（{_sandbox_exec_detail}）",
                    f"docker 不可用（{_docker_probe_detail}）",
                    "bwrap 不参与 darwin auto 探测（darwin 顺序：sandbox-exec → docker）",
                ]
                nested = _sandbox_exec_nested_note()
                if nested:
                    why_none.append(nested)
                _auto_cache = ("none", why_none)
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


def validate_file_binds(
    binds: Sequence[tuple[str, str, str]] | None,
) -> list[tuple[str, str, str]]:
    """host-grant 单文件绑定校验（fail-closed，DESIGN-20261114 §4）.

    每项 (host_path, sandbox_path, "ro"|"rw")：host 必须是**既存常规文件**且
    本身不是 symlink（realpath 归一由授权层完成，此处拒绝符号链接本体）；
    两个路径都必须绝对；access 仅 ro/rw。
    """
    out: list[tuple[str, str, str]] = []
    for item in binds or ():
        try:
            host, sbx, access = item
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid file bind entry: {item!r}") from exc
        host, sbx, access = str(host), str(sbx), str(access)
        if access not in ("ro", "rw"):
            raise ValueError(f"file bind access must be ro|rw, got {access!r}")
        if not os.path.isabs(host) or not os.path.isabs(sbx):
            raise ValueError("file bind paths must be absolute")
        if os.path.islink(host):
            raise ValueError(f"file bind host is a symlink (refused): {host}")
        if not os.path.isfile(host):
            raise ValueError(f"file bind host is not an existing regular file: {host}")
        out.append((host, sbx, access))
    return out


def _bwrap_bind_args(host: str, sbx: str, access: str) -> list[str]:
    """单文件 bind 的 bwrap 参数段：缺失祖先目录 --dir 逐级创建，再 ro-bind/bind.

    祖先目录只到父目录为止（dest 文件本身由 bind 挂载点创建）。
    --dir 对已存在目录是 mkdir -p 语义（EEXIST 容忍），系统 ro-bind 目录
    与 /tmp tmpfs 重复 --dir 无害。
    """
    argv: list[str] = []
    sbx_parts = sbx.split("/")
    # sbx_parts 形如 ['', 'home', 'u', 'x', 'f']；祖先从根下第一级到父目录
    for i in range(2, len(sbx_parts)):
        ancestor = "/" + "/".join(sbx_parts[1:i])
        argv += ["--dir", ancestor]
    flag = "--ro-bind" if access == "ro" else "--bind"
    argv += [flag, host, sbx]
    return argv


# P0-3: never treat a model-visible audit directory as an ordinary workspace
# subdirectory. A writable mount/Seatbelt allow on the parent must not grant
# write access to durable Goal/Task/approval records.
_AUDIT_CRITICAL_FILES = frozenset(
    {"goals.jsonl", "tasks.jsonl", "task_claims.jsonl", "escalation_requests.json"}
)


def _inside(path: str, root: str) -> bool:
    """Component-safe containment; no lexical-prefix or ../ ambiguity."""
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _prepare_protected_roots(roots: Iterable[str]) -> list[str]:
    """Preflight trusted audit roots; reject existing hardlink aliases.

    A pre-existing hardlink outside the denied path can mutate the SAME inode
    despite a macOS path deny or a Linux read-only bind. Fail before spawn.
    An untrusted child cannot create new hardlinks from the protected path once
    the policy is applied (macOS real test; Linux still needs native e2e).
    """
    prepared: list[str] = []
    for raw in roots:
        if not raw:
            continue
        path = os.path.abspath(os.path.expanduser(os.fspath(raw)))
        if os.path.islink(path):
            raise RuntimeError("protected audit root is a symlink (fail-closed)")
        real = os.path.realpath(path)
        if real == os.sep or not os.path.isdir(real):
            raise RuntimeError("protected audit root is missing or unsafe (fail-closed)")
        if real in prepared:
            continue
        try:
            for directory, dirs, files in os.walk(
                real, followlinks=False,
                onerror=lambda exc: (_ for _ in ()).throw(exc),
            ):
                for name in (*dirs, *files):
                    item = os.path.join(directory, name)
                    info = os.lstat(item)
                    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                        raise RuntimeError(
                            "protected audit contains pre-existing hardlink alias (fail-closed)"
                        )
                    if stat.S_ISLNK(info.st_mode) and name in _AUDIT_CRITICAL_FILES:
                        raise RuntimeError(
                            "protected audit critical ledger is a symlink (fail-closed)"
                        )
        except OSError as exc:
            raise RuntimeError(
                f"protected audit cannot be inspected ({type(exc).__name__}; fail-closed)"
            ) from exc
        prepared.append(real)
    return prepared


def _audit_overlay_roots(workdir: str, protected_roots: Iterable[str]) -> list[str]:
    """Overlay only audit roots reachable inside the writable workspace mount.

    Outside roots must NOT be mounted: that would disclose host audit records
    to a sandbox which previously could not see them.
    """
    cwd = os.path.realpath(workdir)
    result: list[str] = []
    for root in protected_roots:
        protected = os.path.realpath(root)
        if _inside(cwd, protected):
            raise RuntimeError("workdir overlaps protected audit (fail-closed)")
        if _inside(protected, cwd):
            result.append(protected)
    return result


def _audit_ancestor_mounts(workdir: str, protected_roots: Iterable[str]) -> list[str]:
    """Pin each writable parent as a mountpoint, preventing rename-away bypass.

    Linux bwrap/docker: an audit-only read-only overlay is insufficient:
    `mv data data_old` can move the protected mount, then a new data/audit
    can be created at the old location. A writable self-bind on each ancestor
    makes its rename fail EBUSY without preventing writes to sibling files.
    """
    cwd = os.path.realpath(workdir)
    ancestors: set[str] = set()
    for root in _audit_overlay_roots(workdir, protected_roots):
        parent = os.path.dirname(root)
        while parent != cwd:
            ancestors.add(parent)
            parent = os.path.dirname(parent)
    return sorted(ancestors, key=lambda p: (p.count(os.sep), p))


def bwrap_argv(
    command: str,
    workdir: str,
    *,
    extra_file_binds: Sequence[tuple[str, str, str]] | None = None,
    protected_roots: Iterable[str] = (),
) -> list[str]:
    """构造 bwrap argv（shell=False 执行，避免 shell=True 引号地狱）.

    extra_file_binds（DESIGN-20261114 host-grant）：授权单文件精确 bind——
    (host_path, sandbox_path, "ro"|"rw")，挂载点祖链 --dir 逐级创建。
    bind 段位于系统 ro-bind 之后、workdir bind 之前。
    """
    argv = [
        "bwrap",
        "--unshare-pid",
        "--unshare-uts",
        "--unshare-ipc",
    ]
    for path in _BWRAP_RO_BINDS:
        argv += ["--ro-bind", path, path]
    argv += ["--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp"]
    for host, sbx, access in validate_file_binds(extra_file_binds):
        argv += _bwrap_bind_args(host, sbx, access)
    argv += ["--bind", workdir, workdir]
    for parent in _audit_ancestor_mounts(workdir, protected_roots):
        # Pin writable ancestors: moving a parent must not relocate the
        # protected mount and allow a forged replacement at the old path.
        argv += ["--bind", parent, parent]
    for root in _audit_overlay_roots(workdir, protected_roots):
        # Read-only overlay AFTER all writable self-binds.
        argv += ["--ro-bind", root, root]
    argv += ["--chdir", workdir]
    argv += ["/bin/sh", "-c", command]
    return argv


def docker_argv(
    command: str, workdir: str, *, image: str = _DEFAULT_IMAGE,
    protected_roots: Iterable[str] = (),
) -> list[str]:
    """构造 docker run argv（容器后端）.

    - --network=none: 断网（严于 bwrap）
    - --read-only + 工作区 bind rw: rootfs 只读, 仅工作区可写
    - --user uid:gid: 容器进程与宿主当前用户同 uid, bind-mount 内新建文件不变成 root 属主
    - --cap-drop ALL / --pids-limit: 收紧能力与进程数
    """
    image = str(image or _DEFAULT_IMAGE).strip() or _DEFAULT_IMAGE
    uid, gid = os.getuid(), os.getgid()
    argv = [
        "docker", "run", "--rm",
        "--network=none",
        "--read-only",
        "--cap-drop", "ALL",
        "--pids-limit", "256",
        "--tmpfs", "/tmp:rw,size=64m",
        "--user", f"{uid}:{gid}",
        "--volume", f"{workdir}:{workdir}:rw",
    ]
    for parent in _audit_ancestor_mounts(workdir, protected_roots):
        if "," in parent:
            raise RuntimeError("docker protected audit mount contains comma (fail-closed)")
        argv += ["--mount", f"type=bind,source={parent},target={parent}"]
    for root in _audit_overlay_roots(workdir, protected_roots):
        if "," in root:
            raise RuntimeError("docker protected audit mount contains comma (fail-closed)")
        argv += ["--mount", f"type=bind,source={root},target={root},readonly"]
    argv += ["--workdir", workdir, image, "sh", "-c", command]
    return argv


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


def sandbox_exec_profile(
    writable_roots: Iterable[str], *, protected_roots: Iterable[str] = ()
) -> str:
    """Seatbelt write allow with final deny for audit and ancestor renames.

    A subpath deny alone is NOT sufficient: renaming its writable parent
    changes the path and bypasses the rule. Literal denies on each ancestor
    prevent that rename while still allowing ordinary sibling file creation.
    """
    allows = "".join(
        f'(allow file-write* (subpath "{_sbx_escape(os.fspath(root))}"))'
        for root in writable_roots
    )
    denies: list[str] = []
    seen: set[str] = set()
    for root in protected_roots:
        real = os.path.realpath(os.fspath(root))
        rule = f'(deny file-write* (subpath "{_sbx_escape(real)}"))'
        if rule not in seen:
            seen.add(rule)
            denies.append(rule)
        parent = os.path.dirname(real)
        while parent and parent != os.sep:
            rule = f'(deny file-write* (literal "{_sbx_escape(parent)}"))'
            if rule not in seen:
                seen.add(rule)
                denies.append(rule)
            parent = os.path.dirname(parent)
    return f"(version 1)(allow default)(deny file-write*){allows}{''.join(denies)}"


def sandbox_exec_argv(
    command: str, workdir: str, *, writable_roots: Iterable[str] = (),
    protected_roots: Iterable[str] = (),
) -> list[str]:
    """构造 sandbox-exec argv（仅 darwin；调用方 Popen shell=False 执行）."""
    profile = sandbox_exec_profile(
        macos_writable_roots(workdir, extra=writable_roots),
        protected_roots=protected_roots,
    )
    return [_SANDBOX_EXEC, "-p", profile, "/bin/bash", "-lc", command]


def _file_binds_note(file_binds: Sequence[tuple[str, str, str]]) -> str:
    """grant 单文件 bind 的 note（S2-6 如实描述，不夸大）。"""
    if not file_binds:
        return ""
    parts = [
        f"{access}:{sbx}" for _h, sbx, access in file_binds
    ]
    return (
        "（host-grant 单文件精确绑定已生效：" + "、".join(parts) + "；"
        "仅授权文件可见/可写，其余路径不变）"
    )


_DROPPED_ROOTS_NOTE = (
    "（注意：writable_roots 仅 sandbox-exec 后端消费，当前后端未强制追加可写根）"
)


def _note_with_dropped_roots(note: str, writable_roots: Sequence[str] | None) -> str:
    """bwrap/docker 不消费 writable_roots：非空时在 note 里明示被忽略。

    T05 审查 P2-2：静默丢弃追加根会让调用方误以为它们已生效。
    """
    if not writable_roots:
        return note
    return note + _DROPPED_ROOTS_NOTE


def sandbox_argv(
    command: str,
    workdir: str,
    *,
    mode: str = "none",
    image: str = _DEFAULT_IMAGE,
    writable_roots: Sequence[str] = (),
    extra_file_binds: Sequence[tuple[str, str, str]] | None = None,
    protected_roots: Sequence[str] = (),
) -> tuple[list[str] | None, str]:
    """按 EXEC_SANDBOX 返回 (argv, note)。

    - none → (None, "")（调用方走既有 shell=True 路径，零回归；note 不加任何"已隔离"措辞）
    - auto → 解析到具体后端后按该后端执行；解析到 none：非 strict 同 none（已先行写
      warning），EXEC_SANDBOX_STRICT=1 → RuntimeError（fail-closed，回执如实失败）。
      若 none 是因为 sandbox-exec 套用被拒，note 会带上"未套内层沙箱、写入边界仅由
      外层决定"的探测结论（不宣称隔离）；其余不可用原因的 note 为空，原因见 warning。
    - bwrap/docker/sandbox-exec 且可用 → (argv, note)（note 文案与实际后端一一对应，S2-6）
    - 显式开启但后端不可用 → 抛 RuntimeError（fail-closed，调用方如实失败回执）
    - writable_roots（T05）：追加可写根，仅 sandbox-exec 后端消费——原样透传
      ``sandbox_exec_argv``（叠加进 profile 的 allow subpath）；bwrap/docker 的可写域
      结构性固定为工作区（无追加根机制），该参数对它们无效果。默认 ``()`` 与不传
      完全等价（既有行为字节级不变）。
    - extra_file_binds（DESIGN-20261114 host-grant P0）：授权单文件精确 bind，
      (host, sandbox, "ro"|"rw")。bwrap → 精确 --ro-bind/--bind（含 --dir 祖链）；
      sandbox-exec → rw 项追加 writable_roots（ro 项读侧本就不受限）；docker →
      拒绝（P0 未实现）；none → 调用方必须先行拒绝（本函数返回无沙箱 argv，
      grant 边界将不存在）。默认 None 与不传完全等价。
    """
    mode = sandbox_mode(mode)
    file_binds = validate_file_binds(extra_file_binds)
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
            note = _sandbox_exec_nested_note()
            if protected_roots:
                note += "（警告：auto 降级 none；审计账本未受沙箱写隔离）"
            return (None, note)
        mode = backend
    if mode == "none":
        return (
            None,
            "（警告：EXEC_SANDBOX=none；审计账本未受沙箱写隔离）"
            if protected_roots else "",
        )
    protected = _prepare_protected_roots(protected_roots)
    for host, sbx, _access in file_binds:
        if any(
            _inside(os.path.realpath(candidate), root)
            for root in protected
            for candidate in (host, sbx)
        ):
            raise RuntimeError("host-grant overlaps protected audit (fail-closed)")
    if mode == "bwrap":
        if shutil.which("bwrap") is None:
            raise RuntimeError(
                "EXEC_SANDBOX=bwrap 已显式配置，但系统找不到 bwrap（bubblewrap）——"
                "fail-closed：命令未执行。请安装 bubblewrap（Linux: apt install bubblewrap）"
                "或改用 EXEC_SANDBOX=docker（macOS 可用）或 EXEC_SANDBOX=none。"
            )
        binds_note = _file_binds_note(file_binds)
        return (
            bwrap_argv(
                command, workdir, extra_file_binds=file_binds,
                protected_roots=protected,
            ),
            _note_with_dropped_roots(
                _BWRAP_NOTE + binds_note + (_AUDIT_PROTECTED_NOTE if protected else ""),
                writable_roots,
            ),
        )
    if mode == "docker":
        if file_binds:
            raise RuntimeError(
                "EXEC_SANDBOX=docker 后端暂不支持 host-grant 单文件绑定"
                "（P0 范围：bwrap / sandbox-exec）——fail-closed：命令未执行。"
            )
        if shutil.which("docker") is None:
            raise RuntimeError(
                "EXEC_SANDBOX=docker 已显式配置，但系统找不到 docker CLI——"
                "fail-closed：命令未执行。请安装/启动 Docker Desktop "
                f"（镜像可用 EXEC_SANDBOX_IMAGE 指定，默认 {_DEFAULT_IMAGE}）"
                "或设 EXEC_SANDBOX=none。"
            )
        return (
            docker_argv(command, workdir, image=image, protected_roots=protected),
            _note_with_dropped_roots(
                _DOCKER_NOTE + (_AUDIT_PROTECTED_NOTE if protected else ""),
                writable_roots,
            ),
        )
    if mode == "sandbox-exec":
        if not _probe_sandbox_exec():
            raise RuntimeError(
                "EXEC_SANDBOX=sandbox-exec 已显式配置，但当前不可用"
                f"（{_sandbox_exec_detail}）{_sandbox_exec_nested_note()}"
                "——fail-closed：命令未执行。"
                "可改用 EXEC_SANDBOX=auto 自动解析或 EXEC_SANDBOX=none。"
            )
        grant_roots = [sbx for _h, sbx, access in file_binds if access == "rw"]
        return (
            sandbox_exec_argv(
                command,
                workdir,
                writable_roots=[*writable_roots, *grant_roots],
                protected_roots=protected,
            ),
            _SANDBOX_EXEC_NOTE + _file_binds_note(file_binds)
            + (_AUDIT_PROTECTED_NOTE if protected else ""),
        )
    return (None, "")


# 便捷签名（测试/调用方断言用）
Builder = Callable[[str, str], list[str]]
