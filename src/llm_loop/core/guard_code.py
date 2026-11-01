"""守卫模块代码指纹与源码树定位（守卫层专用原语，零第三方依赖）.

为什么是 core：``runtime``（manifest / service_control）与 ``introspection``
（proc_version）都需要"改了守卫代码但进程还在跑旧字节码"的同一份判据。判据放在
introspection 会让 runtime 新增跨 plane 反向依赖——Kernel v1 import ratchet 实测
拦截（runtime->introspection）；放在 core 则两侧都能用，且本模块不向上层反向依赖。

判据分层见 ``proc_version.guard_code_drift``：stale 只对"本进程已 import 的模块"
成立；不可判定一律 None / unknown，绝不退化成"一致"。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# 声明的相对路径以 llm_loop 包根为基准；新增守卫模块必须同步追加
# （tests/unit/test_guard_code_freshness.py 断言每条都存在，防止改名后静默失配）。
GUARD_MODULES: tuple[str, ...] = (
    "core/command_scope_guard.py",
    "tools/safety.py",
    "security_guard.py",
    "sealed_paths.py",
    "net_guard.py",
)

# 判断"目录里是不是本包"的最小充分条件
_SENTINEL = "core/command_scope_guard.py"


def package_root() -> Path:
    """本模块所在 llm_loop 包根（走 release 目录时指向 release 副本）."""
    return Path(__file__).resolve().parents[1]


def is_llm_loop_package(root: Path) -> bool:
    """该目录是否像一个 llm_loop 包（用于把"不可判定"与"不一致"分开）."""
    return (root / _SENTINEL).is_file()


def module_name(rel: str) -> str:
    stem = rel[:-3] if rel.endswith(".py") else rel
    return "llm_loop." + stem.replace("/", ".")


def guard_code_fingerprint(root: str | Path | None = None) -> dict[str, str]:
    """守卫模块磁盘指纹 {相对路径: sha256 前 16 位}；缺失记 missing，不抛异常."""
    base = Path(root) if root is not None else package_root()
    out: dict[str, str] = {}
    for rel in GUARD_MODULES:
        try:
            out[rel] = hashlib.sha256((base / rel).read_bytes()).hexdigest()[:16]
        except OSError:
            out[rel] = "missing"
    return out


def repo_root_from(loaded_pkg: Path) -> Path | None:
    """从 ``<repo>/.releases/<sha>/src/llm_loop`` 反推 ``<repo>``；非该形态返回 None.

    release 副本自带 .git，``git rev-parse --show-toplevel`` 会停在副本里，故用
    路径结构判定，不做 cwd 探测。
    """
    parts = loaded_pkg.parts
    if ".releases" not in parts:
        return None
    idx = parts.index(".releases")
    if idx == 0:
        return None
    return Path(*parts[:idx])


def repo_source_root() -> Path | None:
    """可编辑源码树的 llm_loop 包根；不可判定返回 None（不读环境变量，纯路径）.

    release 部署 → ``<repo>/src/llm_loop``；直接从源码运行 → 包根本身。
    目录里不含守卫模块（如被拷到别处）→ None，由调用方报 unknown。
    """
    pkg = package_root()
    repo = repo_root_from(pkg)
    candidate = (repo / "src" / "llm_loop") if repo is not None else pkg
    return candidate if is_llm_loop_package(candidate) else None
