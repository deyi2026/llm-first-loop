"""闸4 写侧（T9-a 首切片）：远程写不得成为绕过本地写域的第二条路。

设计来源：DESIGN-20261107 §5.5「闸3 与闸4 必须能各自独立拒绝」。
闸3（``policy.require_path_allowed``）判 grant 的 ``allowed_paths``；本模块判**本机
写域**，两者互不替代：grant 再宽也不能把写域撑大，写域再宽也不能越过 grant。

判定顺序（任一条即可拒绝）：
1. 写域根 ``LFL_PEER_WRITE_ROOT``：必须由本机操作者显式声明。**未配置即全拒**
   （``sandbox_denied`` / ``write_root_not_configured``）——不从 grant 推导默认值，
   避免"给了一个租约就等于开了一条远程写路径"。
2. 目标本身若是 symlink 直接拒绝：``os.replace`` 会替换链接本身而不写穿，但
   "远程能删掉/替换一个链接"仍是域外效应。先判它，避免 realpath 把"链接指向域外"
   折叠成"父目录越界"，让控制端看不出真正原因。
3. 写域根必须是绝对路径，且 realpath 后目标父目录落在根内（按分隔符边界判定，
   故 ``/wr-evil`` 不命中 ``/wr``）。
4. 封条 ``sealed_path_reason``：held-out 材料不允许被远程改写或植入。
5. 敏感路径 ``is_sensitive_path``：闸3 已判，这里做纵深防御（闸3 配置漂移时仍拒）。

已知残余（不声称是沙盒）：
- 不套 bwrap，本模块只做"更窄的写域 + 链接拒绝 + 封条"，不是内核级隔离。
- realpath 与真正 ``os.replace`` 之间有 TOCTOU 窗口；执行器用
  ``mkstemp(dir=父目录)`` + ``os.replace`` 缩小，但不能消除。
- **已存在的硬链接**文件不受 O_NOFOLLOW/链接检查约束：写它会改到 inode 的上游。
  故写域内不应存在指向域外的硬链接（部署约束，非本模块可判）。
- 不校验写入后的配额/磁盘；``ENOSPC`` 等属真实故障，映射 ``executor_internal_error``。
"""

from __future__ import annotations

import os
from typing import Final

from ..sealed_paths import sealed_path_reason
from .errors import PeerError
from .policy import is_sensitive_path

WRITE_ROOT_ENV: Final[str] = "LFL_PEER_WRITE_ROOT"


def peer_write_root_from_env() -> str | None:
    """读本机写域配置；空串/未设置都视作"未声明"。"""
    raw = os.environ.get(WRITE_ROOT_ENV, "")
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    return raw or None


def _norm(path: str) -> str:
    # 不用 Path.resolve()：不存在的路径不抛错，且 realpath 已展开 symlink 与 "..".
    return os.path.realpath(os.path.expanduser(path))


def _within(root: str, target: str) -> bool:
    root = root.rstrip(os.sep)
    if not root:
        return True
    return target == root or target.startswith(root + os.sep)


def require_write_target(path: object, *, write_root: str | None = None) -> str:
    """校验远程写目标；返回 realpath（父目录）供执行器直接落盘。"""
    if not isinstance(path, str) or not path:
        raise PeerError("params_schema_invalid", "path must be a non-empty string")
    if not os.path.isabs(path):
        raise PeerError("params_schema_invalid", f"path must be absolute: {path!r}")

    if os.path.islink(path):
        # 先判链接再解析父目录：否则 realpath 会把"链接指向域外"折叠成
        # target_parent_outside，控制端就看不出真正原因是符号链接。
        raise PeerError("sandbox_denied", "target_is_symlink")

    root_raw = write_root if write_root is not None else peer_write_root_from_env()
    if not root_raw:
        raise PeerError("sandbox_denied", f"write_root_not_configured:{WRITE_ROOT_ENV}")
    if not os.path.isabs(root_raw):
        raise PeerError("sandbox_denied", f"write_root_must_be_absolute:{WRITE_ROOT_ENV}")

    root = _norm(root_raw)
    target = _norm(path)
    parent = os.path.dirname(target) or os.sep
    if not _within(root, parent):
        raise PeerError("sandbox_denied", "target_parent_outside_peer_write_root")

    sealed = sealed_path_reason(target)
    if sealed:
        raise PeerError("sandbox_denied", f"sealed_path:{sealed}"[:200])

    if is_sensitive_path(target):
        raise PeerError("sandbox_denied", "sensitive_path")

    return target
