"""R3 绑定 attestation（DESIGN-20261005 v4 §4.3，S3b；机制按 S0 结论 ②）。

机制：host 侧进程证据（`lsof -t -iTCP:<port> -sTCP:LISTEN` → 唯一 PID →
原生 NUL 分隔 argv 源：macOS `sysctl(KERN_PROCARGS2)`、Linux `/proc/<pid>/cmdline`；
`ps -ww -o command=`+shlex 仅作兜底——ps 输出按空格 join，无法还原参数内空格，
含空格的 `--user-data-dir` 值会被截断 ⇒ 误 fail-closed real，S4-20261006 实测）。
不依赖浏览器自报。S0 四态实测（2026-10-06，
docs/S0-RESULT-20261005-browser-attestation-spike.md）：
- Chrome 154 稳定版 getBrowserCommandLine 无 --enable-automation ⇒ ServerError（自报通道自锁）；
- 加 flag ⇒ navigator.webdriver=true（dedicated 会话被污染，R1 主用例受害）；
- lsof→ps 四态全绿，21-40ms 一次性，无页面副作用。

判定器 v2（§8-F2）按默认 profile 树判别（不按白名单，防误杀 qualification 临时目录）。
一切机制失败/字段缺失/无法解析 ⇒ fail-closed 判 real（F15）。
"""
from __future__ import annotations

import hashlib
import logging
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlsplit

__all__ = [
    "AttestationVerdict",
    "BindingPolicy",
    "VERDICT_DEDICATED",
    "VERDICT_REAL",
    "attest_port",
    "attest_debug_url",
    "builtin_default_trees",
    "classify_user_data_dir",
    "extract_user_data_dir_value",
    "resolve_profile_trees",
    "sha256_argv",
]

logger = logging.getLogger("llm_loop.browser.attestation")

VERDICT_DEDICATED = "dedicated"
VERDICT_REAL = "real"


@dataclass(frozen=True)
class AttestationVerdict:
    verdict: str  # dedicated | real
    user_data_dir: str | None
    argv_sha256: str
    argv: tuple[str, ...] = ()
    detail: str = ""
    checked_at: float = field(default_factory=time.time)


def sha256_argv(argv: Sequence[str]) -> str:
    return hashlib.sha256("\0".join(argv).encode("utf-8")).hexdigest()


def builtin_default_trees() -> tuple[Path, ...]:
    if sys.platform == "darwin":
        candidates = (
            "~/Library/Application Support/Google/Chrome",
            "~/Library/Application Support/Chromium",
        )
    else:
        candidates = ("~/.config/google-chrome", "~/.config/chromium")
    return tuple(Path(os.path.realpath(Path(c).expanduser())) for c in candidates)


def resolve_profile_trees(paths_raw: str) -> tuple[Path, ...] | None:
    """PATHS 解析（§4.2/§4.3 v4-G7）：

    - ""  → 内置默认树；
    - "none" → None（最严档：全判 real）；
    - 非空 → 内置默认树 ∪ 操作者目录（只增不替）。
    相对路径/无法 realpath ⇒ ValueError（上层 fail-closed 判 real）。
    """
    raw = (paths_raw or "").strip()
    if raw == "none":
        return None
    trees = list(builtin_default_trees())
    if raw:
        for item in raw.split(","):
            item = item.strip()
            if not item:
                continue
            if not item.startswith("/"):
                raise ValueError(f"REAL_PROFILE_PATHS 相对路径（须绝对路径）: {item!r}")
            trees.append(Path(os.path.realpath(item)))
    return tuple(trees)


def extract_user_data_dir_value(argv: Sequence[str]) -> str | None:
    """两种 token 形态（§4.3）：`--user-data-dir=V` 与 `--user-data-dir V`。

    多次出现取最后一个（Chromium command line 语义）。返回 None ⇒ 无该 flag。
    """
    value: str | None = None
    tokens = list(argv)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "--user-data-dir" and i + 1 < len(tokens):
            value = tokens[i + 1]
            i += 2
            continue
        if tok.startswith("--user-data-dir="):
            value = tok.split("=", 1)[1]
        i += 1
    return value


def classify_user_data_dir(
    value: str | None, trees: tuple[Path, ...] | None
) -> tuple[str, str]:
    """单值分类 → (verdict, detail)。所有无法可靠解析的分支一律 real（fail-closed）。"""
    if trees is None:
        return VERDICT_REAL, "PATHS=none 最严档：全判 real"
    if value is None:
        return VERDICT_REAL, "argv 无 --user-data-dir（使用默认 profile）"
    if not str(value).startswith("/"):
        return VERDICT_REAL, (
            f"--user-data-dir 相对路径无法可靠解析（Chrome cwd 不可求）fail-closed real: {value!r}"
        )
    try:
        resolved = Path(str(value)).expanduser().resolve(strict=True)
    except OSError as exc:
        return VERDICT_REAL, (
            f"realpath 解析失败（断裂 symlink/不存在）fail-closed real: {value!r}"
            f" ({exc.__class__.__name__}: {exc})"
        )
    for tree in trees:
        if resolved == tree or resolved.is_relative_to(tree):
            return VERDICT_REAL, f"realpath {resolved} 落默认/授权树内 {tree}（指回默认 profile）"
    return VERDICT_DEDICATED, f"realpath {resolved} 在默认/授权树外（隔离 profile）"


def _listen_pids(port: int) -> list[str]:
    out = subprocess.run(
        ["lsof", "-nP", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
        capture_output=True, text=True, timeout=5,
    )
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def _parse_proc_cmdline(data: bytes) -> list[str]:
    """Linux `/proc/<pid>/cmdline`：NUL 分隔，空参数与尾 NUL 剔除。空/无参 ⇒ ValueError。"""
    argv = [p.decode("utf-8", "replace") for p in data.split(b"\x00") if p != b""]
    if not argv:
        raise ValueError("cmdline 无 NUL 分隔参数（内核线程/空）")
    return argv


def _linux_cmdline_argv(pid: str) -> list[str]:
    with open(f"/proc/{pid}/cmdline", "rb") as fh:
        return _parse_proc_cmdline(fh.read())


def _parse_procargs2(data: bytes) -> list[str]:
    """macOS `sysctl(KERN_PROCARGS2)` 布局：[argc:int32][exec path\\0][NUL padding][argv 各\\0 结尾]。

    解析出恰好 argc 个 NUL 结尾字符串（保留参数内空格）；畸形/空 ⇒ ValueError。
    """
    if len(data) < 4:
        raise ValueError(f"procargs2 缓冲过短: {len(data)}B")
    argc = int.from_bytes(data[:4], sys.byteorder)
    if not 1 <= argc <= 8192:
        raise ValueError(f"procargs2 argc 越界: {argc}")
    nul = data.find(b"\x00", 4)  # exec path 结束处
    if nul == -1:
        raise ValueError("procargs2 无 exec path 终止符")
    off = nul + 1
    while off < len(data) and data[off] == 0:  # argv 起点前的对齐 padding
        off += 1
    argv: list[str] = []
    for _ in range(argc):
        end = data.find(b"\x00", off)
        if end == -1:
            break  # 内核截断：不足 argc 个完整串
        argv.append(data[off:end].decode("utf-8", "replace"))
        off = end + 1
    if not argv:
        raise ValueError("procargs2 未解析出任何 argv")
    return argv


def _macos_procargs2_argv(pid: str) -> list[str]:
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    sysctl = libc.sysctl
    sysctl.argtypes = [
        ctypes.POINTER(ctypes.c_int), ctypes.c_uint,
        ctypes.c_char_p, ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_char_p, ctypes.c_size_t,
    ]
    sysctl.restype = ctypes.c_int
    mib = (ctypes.c_int * 3)(1, 49, int(pid))  # CTL_KERN, KERN_PROCARGS2, pid
    size = ctypes.c_size_t(0)
    if sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), f"sysctl(KERN_PROCARGS2,{pid}) size")
    if size.value <= 0:
        raise ValueError(f"procargs2 size={size.value}")
    buf = ctypes.create_string_buffer(size.value)
    if sysctl(mib, 3, buf, ctypes.byref(size), None, 0) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), f"sysctl(KERN_PROCARGS2,{pid}) fetch")
    return _parse_procargs2(buf.raw[: size.value])


def _native_argv(pid: str) -> list[str] | None:
    """平台原生 NUL 分隔 argv 源（保留参数内空格）。无源/失败 ⇒ None（上层回落 ps）。"""
    if sys.platform == "darwin":
        try:
            return _macos_procargs2_argv(pid)
        except Exception as exc:  # noqa: BLE001 - 回落兜底源，不改变 fail-closed 契约
            logger.warning(
                "KERN_PROCARGS2 读取失败，回落 ps（含空格参数可能被截断）: pid=%s %r", pid, exc,
            )
    elif sys.platform == "linux":
        try:
            return _linux_cmdline_argv(pid)
        except Exception as exc:  # noqa: BLE001
            logger.warning("/proc/%s/cmdline 读取失败，回落 ps: %r", pid, exc)
    return None


def _ps_argv(pid: str) -> list[str]:
    """兜底源：ps 文本按空格 join 后 shlex 猜切分，**无法还原参数内空格**（S4 已知限制）。"""
    out = subprocess.run(
        ["ps", "-ww", "-o", "command=", "-p", pid],
        capture_output=True, text=True, timeout=5,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ps exit={out.returncode}")
    return shlex.split(out.stdout.strip())


def _pid_argv(pid: str) -> list[str]:
    argv = _native_argv(pid)
    if argv is not None:
        return argv
    return _ps_argv(pid)


def attest_port(port: int, trees: tuple[Path, ...] | None) -> AttestationVerdict:
    """host 侧机制：lsof→唯一 PID→原生 argv→判定器 v2。任何一步失败 ⇒ fail-closed real。"""

    def _real(detail: str, argv: Sequence[str] = ()) -> AttestationVerdict:
        return AttestationVerdict(
            verdict=VERDICT_REAL,
            user_data_dir=extract_user_data_dir_value(argv) if argv else None,
            argv_sha256=sha256_argv(argv) if argv else "",
            argv=tuple(argv),
            detail=detail,
        )

    try:
        pids = _listen_pids(port)
    except Exception as exc:  # noqa: BLE001 - fail-closed 契约
        return _real(f"lsof 调用失败 fail-closed real: {exc!r}")
    if not pids:
        return _real(f"端口 {port} 无监听 PID（Chrome 未起/已退）fail-closed real")
    if len(pids) > 1:
        return _real(f"端口 {port} 监听 PID 不唯一 {pids} fail-closed real")
    try:
        argv = _pid_argv(pids[0])
    except Exception as exc:  # noqa: BLE001
        return _real(f"argv 读取失败 fail-closed real: {exc!r}")
    value = extract_user_data_dir_value(argv)
    verdict, detail = classify_user_data_dir(value, trees)
    return AttestationVerdict(
        verdict=verdict,
        user_data_dir=value,
        argv_sha256=sha256_argv(argv),
        argv=tuple(argv),
        detail=f"pid={pids[0]}; {detail}",
    )


def attest_debug_url(debug_base_url: str, paths_raw: str = "") -> AttestationVerdict:
    """host 绑定路径默认入口：debug_base_url → port → attest_port（PATHS 语义同上）。"""
    try:
        port = urlsplit(debug_base_url).port or 80
    except ValueError:
        return AttestationVerdict(
            verdict=VERDICT_REAL, user_data_dir=None, argv_sha256="",
            detail=f"debug_base_url 解析失败 fail-closed real: {debug_base_url!r}",
        )
    try:
        trees = resolve_profile_trees(paths_raw)
    except ValueError as exc:
        return AttestationVerdict(
            verdict=VERDICT_REAL, user_data_dir=None, argv_sha256="",
            detail=f"PATHS 解析失败 fail-closed real: {exc}",
        )
    return attest_port(port, trees)


@dataclass(frozen=True)
class BindingPolicy:
    """授权策略（§4.3-F14）：缺省 deny_real —— 直连入口零改动即默认 fail-closed。"""

    allow_real: bool = False
    ack_digest: str | None = None
    mode: str = "enforce"  # shadow | enforce（v4-G6）

    @classmethod
    def deny_real(cls, mode: str = "enforce") -> "BindingPolicy":
        return cls(allow_real=False, ack_digest=None, mode=mode)

    @classmethod
    def permit_real(cls, ack_digest: str, mode: str = "enforce") -> "BindingPolicy":
        return cls(allow_real=True, ack_digest=ack_digest, mode=mode)

    def check(self, verdict: AttestationVerdict) -> tuple[bool, str]:
        """返回 (allowed, reason)。shadow 模式永不拒绝，但把"enforce 下会拒"写进 reason 与日志。"""
        if verdict.verdict == VERDICT_DEDICATED:
            return True, f"verdict=dedicated（{verdict.detail}）"
        if self.allow_real:
            return True, (
                f"verdict=real 由 policy 放行（ack_digest={self.ack_digest}; {verdict.detail}）"
            )
        if self.mode == "shadow":
            logger.info(
                "attestation SHADOW: verdict=real would be refused under enforce "
                "(argv_sha256=%s detail=%s)",
                verdict.argv_sha256, verdict.detail,
            )
            return True, (
                f"shadow: enforce 下将拒绝（verdict=real; argv_sha256={verdict.argv_sha256}; "
                f"{verdict.detail}）"
            )
        return False, (
            f"verdict=real 且无 allow-real policy —— fail-closed 拒绝绑定"
            f"（argv_sha256={verdict.argv_sha256}; {verdict.detail}; "
            "需要 LFL_BROWSER_PROFILE_CLASS=real + REAL_PROFILE_ACK，或改用 dedicated profile）"
        )
