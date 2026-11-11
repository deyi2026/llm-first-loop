"""任务执行器（受控端）：已实现 ``fs.read`` / ``fs.list`` / ``fs.write``。

设计约束（DESIGN §5.4/§5.5）：
- 闸3（policy）已判定 kind/租约/路径；执行器**再解析一次** realpath 并用
  ``O_NOFOLLOW`` 打开，把"策略判定的路径"与"实际读的路径"绑成同一个，
  减小 TOCTOU 窗口（残余：realpath 与实际 inode 之间的窗口仍存在，故仍依赖闸4）。
- 产物不内联：内容一律进 ArtifactStore，回执只带 ``artifact://v1/<sha256>``。
- 未实现的 kind 明确拒绝（``policy_task_kind_not_allowed`` + detail ``handler_missing``），
  不假装成功、不返回空结果。
- ``desktop.*`` 先判显示协议：非 X11（Wayland/none）一律 ``unsupported_display_protocol``。
  理由：X11 采集与注入依赖 Xlib，Wayland 下不存在等价语义，"试一下再看"会把
  "协议不支持"伪装成"执行失败"，控制端无法据此决定是否改派。
- 写侧（T9-a）：``fs.write`` 在闸3 之后再走闸4 ``write_gate``（本机写域 + 链接拒绝 +
  封条 + 敏感路径），原子落盘（同目录 mkstemp + ``os.replace``），回执只带
  ``sha256``/字节数，不回显内容。

状态与边界：
- ``fs.write`` 执行器与监督通道（T9-b）均已就绪：``kinds.EXECUTABLE_KINDS`` 含 ``fs.write``，
  但它是 ``supervised_only``——只有监督开启且 write_root/operator 可用时 manifest 才播报；
  未监督的提交仍一律 ``requires_supervised_execution``。
- 未实现：``shell.exec`` / ``desktop.*``（需要 X11 采集或进程沙盒，属有人在场路径）。
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import errno
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

from .artifacts import ArtifactStore
from .errors import PeerError
from .policy import DEFAULT_MAX_READ_BYTES, require_path_allowed
from .write_gate import require_write_target

MAX_LIST_ENTRIES = 500
MAX_WRITE_BYTES = 1_048_576
# 1 MiB 正文的 base64 编码上界：先按编码长度设界，再解码（避免先吃满内存才拒）。
MAX_WRITE_B64_CHARS = 4 * ((MAX_WRITE_BYTES + 2) // 3)


@dataclass(frozen=True)
class ExecOutcome:
    summary: str
    artifacts: tuple[dict[str, Any], ...] = field(default_factory=tuple)


class Executor:
    def __init__(
        self,
        *,
        artifacts: ArtifactStore,
        node_id: str,
        write_root: str | None = None,
    ) -> None:
        self._artifacts = artifacts
        self._node_id = node_id
        # None = 写域未声明（闸4 全拒）；本类不读进程环境，值由装配层注入
        # （config.PeerSettings.peer_write_root / peer_serve --write-root）。
        self._write_root = write_root

    def run(
        self,
        *,
        kind: str,
        params: dict[str, Any],
        allowed_paths: tuple[str, ...],
        display_protocol: str = "none",
    ) -> ExecOutcome:
        handler = getattr(self, "_run_" + kind.replace(".", "_"), None)
        if handler is None:
            if kind.startswith("desktop.") and display_protocol != "x11":
                raise PeerError(
                    "unsupported_display_protocol",
                    f"{kind} requires x11,这一端是 {display_protocol!r}",
                )
            raise PeerError("policy_task_kind_not_allowed", f"handler_missing:{kind}")
        return handler(params=params, allowed_paths=allowed_paths)

    # --- handlers -----------------------------------------------------------
    def _run_fs_read(self, *, params: dict[str, Any], allowed_paths: tuple[str, ...]) -> ExecOutcome:
        target = self._open_regular_file(params["path"], allowed_paths)
        limit = int(params.get("max_bytes", DEFAULT_MAX_READ_BYTES))
        with os.fdopen(target, "rb") as fh:
            data = fh.read(limit + 1)
        truncated = len(data) > limit
        payload = data[:limit]
        descriptor = self._artifacts.put(payload, media_type=_media_type(payload))
        summary = f"read {len(payload)} bytes from {params['path']}"
        if truncated:
            summary += f" (truncated at max_bytes={limit})"
        return ExecOutcome(summary=summary, artifacts=(descriptor,))

    def _run_fs_list(self, *, params: dict[str, Any], allowed_paths: tuple[str, ...]) -> ExecOutcome:
        root = require_path_allowed(params["path"], allowed_paths)
        if not os.path.isdir(root):
            raise PeerError("params_schema_invalid", f"not a directory: {params['path']!r}")
        depth = int(params.get("depth", 1))
        entries, truncated = _walk_bounded(root, depth)
        payload = json.dumps(
            {"root": root, "depth": depth, "entries": entries, "truncated": truncated},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        descriptor = self._artifacts.put(payload, media_type="application/json")
        summary = f"listed {len(entries)} entries under {params['path']} (depth={depth})"
        if truncated:
            summary += f" (truncated at {MAX_LIST_ENTRIES} entries)"
        return ExecOutcome(summary=summary, artifacts=(descriptor,))

    def _run_fs_write(self, *, params: dict[str, Any], allowed_paths: tuple[str, ...]) -> ExecOutcome:
        # 顺序固定：闸4（本机写域/链接/封条/敏感）→ 闸3 复核 → 内容解析 → 原子落盘。
        # 闸3 在准入侧已判过 grant allowlist，这里复核是因为执行器可被单独调用；
        # 两道闸各自独立拒绝，不互相替代。
        raw_path = params.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            # 缺 path 键不再以 KeyError 冒到路由层（500/不可判定）；按参数错误 fail-closed。
            raise PeerError("params_schema_invalid", "path must be a non-empty string")
        target = require_write_target(raw_path, write_root=self._write_root)
        require_path_allowed(target, allowed_paths)

        payload = self._write_payload(params)
        if len(payload) > MAX_WRITE_BYTES:
            raise PeerError("params_schema_invalid", f"content exceeds {MAX_WRITE_BYTES} bytes")

        parent = os.path.dirname(target)
        if not os.path.isdir(parent):
            if not params.get("create_parents", False):
                raise PeerError("params_schema_invalid", "parent directory does not exist")
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError as exc:
                raise PeerError("sandbox_denied", f"cannot create parent: {exc.strerror}") from None
            # 新建目录后重新过闸：并发替换中间目录可让父目录 realpath 落到域外。
            target = require_write_target(params["path"], write_root=self._write_root)
            require_path_allowed(target, allowed_paths)

        if not params.get("overwrite", False) and os.path.lexists(target):
            raise PeerError("params_schema_invalid", "target exists and overwrite=false")

        dir_synced = self._atomic_write(
            target, payload, replace_existing=bool(params.get("overwrite", False))
        )
        digest = hashlib.sha256(payload).hexdigest()
        summary = f"wrote {len(payload)} bytes to {target} (sha256={digest})"
        if not dir_synced:
            # §6.2：提交后目录项同步失败 → 标记待核对，不得伪装成确定状态。
            summary += " [dir-sync-pending]"
        return ExecOutcome(summary=summary)

    # --- helpers ------------------------------------------------------------
    def _write_payload(self, params: dict[str, Any]) -> bytes:
        """内容源二选一由闸3 ``validate_params`` 保证；这里只解，不再兜底。"""
        if "content_b64" in params:
            encoded = params["content_b64"]
            # 先按编码长度设界再解码：否则超长 base64 会先把内存吃满，再被 1 MiB 上限拒。
            if not isinstance(encoded, str) or len(encoded) > MAX_WRITE_B64_CHARS:
                raise PeerError(
                    "params_schema_invalid",
                    f"content_b64 must be a string of at most {MAX_WRITE_B64_CHARS} chars",
                )
            try:
                payload = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                raise PeerError("params_schema_invalid", "content_b64 is not valid base64") from None
            if len(payload) > MAX_WRITE_BYTES:
                raise PeerError("params_schema_invalid", f"content exceeds {MAX_WRITE_BYTES} bytes")
            return payload
        return self._artifacts.read(params["artifact_ref"])

    @staticmethod
    def _atomic_write(target: str, payload: bytes, *, replace_existing: bool) -> bool:
        """原子提交（§6.1）：新建走 ``link(2)`` 发布，目标存在与否由内核原子判定，
        不存在「检查后覆盖」竞态；覆盖仅在调用方（管理锁+快照复核）许可下用
        ``rename`` 原子替换。返回父目录项是否已同步。

        临时名携带归属前缀（当前进程级；引入 attempt 记录后升级）。
        link 发布成功后、移除临时名之前崩溃：目标与临时名同 inode（nlink>=2）
        是「已发布」的强证据——清理失败不得把提交伪装成失败。
        """
        parent = os.path.dirname(target)
        try:
            fd, tmp = tempfile.mkstemp(
                dir=parent, prefix=f".lfl-peer-write-p{os.getpid()}-"
            )
        except OSError as exc:
            raise PeerError("sandbox_denied", f"cannot create temp file: {exc.strerror}") from None
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, _file_mode_for(target))
            if replace_existing:
                os.replace(tmp, target)
            else:
                try:
                    os.link(tmp, target)
                except OSError as exc:
                    if exc.errno == errno.EEXIST:
                        with contextlib.suppress(OSError):
                            os.unlink(tmp)
                        raise PeerError(
                            "params_schema_invalid", "target exists and overwrite=false"
                        ) from None
                    if exc.errno in (
                        errno.EOPNOTSUPP,
                        errno.ENOSYS,
                        errno.EPERM,
                        errno.EXDEV,
                    ):
                        with contextlib.suppress(OSError):
                            os.unlink(tmp)
                        raise PeerError(
                            "sandbox_denied",
                            f"atomic publish (link) unsupported: {exc.strerror}",
                        ) from None
                    raise
                # 发布成功即已提交；移除临时名失败不改写提交事实（nlink>=2 强证据）
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
            return _fsync_dir(parent)
        except OSError as exc:
            # replace 已成功时 tmp 不存在；清理失败不改变主错误
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            if exc.errno in (errno.EACCES, errno.EPERM, errno.EROFS, errno.EXDEV):
                raise PeerError("sandbox_denied", f"write refused: {exc.strerror}") from None
            raise PeerError("executor_internal_error", f"write failed: {exc.strerror}") from None

    def _open_regular_file(self, path: str, allowed_paths: tuple[str, ...]) -> int:
        real = require_path_allowed(path, allowed_paths)
        if not os.path.isfile(real):
            raise PeerError("params_schema_invalid", f"not a regular file: {path!r}")
        try:
            return os.open(real, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise PeerError("path_outside_allowed_paths", f"symlink swap: {path!r}") from None
            if exc.errno in (errno.EACCES, errno.EPERM):
                raise PeerError("sandbox_denied", f"permission denied: {path!r}") from None
            raise


def _current_umask() -> int:
    current = os.umask(0)
    os.umask(current)
    return current


# 导入期只读一次 umask：运行期不再改动进程 umask，避免线程间竞态把并发创建的文件放宽。
_DEFAULT_FILE_MODE = 0o666 & ~_current_umask()


def _file_mode_for(target: str) -> int:
    """覆盖写沿用原文件权限位；新文件按 umask 推导，不再硬写 0644 放宽。"""
    try:
        return os.stat(target).st_mode & 0o777
    except OSError:
        return _DEFAULT_FILE_MODE


def _fsync_dir(path: str) -> bool:
    """父目录项同步（W3；operator._fsync_dir 同款模式）。失败返回 False，
    由调用方在结果上标记待核对——文件级 fsync 不覆盖目录项。"""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return False
    try:
        os.fsync(fd)
    except OSError:
        return False
    else:
        return True
    finally:
        os.close(fd)


def _media_type(payload: bytes) -> str:
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"
    return "text/plain"


def _walk_bounded(root: str, depth: int) -> tuple[list[dict[str, Any]], bool]:
    """有界遍历：不跟随目录符号链接（防越界），条目数与深度都封顶。"""
    entries: list[dict[str, Any]] = []
    frontier: list[tuple[str, int]] = [(root, 0)]
    truncated = False
    while frontier:
        current, level = frontier.pop(0)
        try:
            with os.scandir(current) as it:
                for item in it:
                    if len(entries) >= MAX_LIST_ENTRIES:
                        return entries, True
                    try:
                        is_dir = item.is_dir(follow_symlinks=False)
                        is_link = item.is_symlink()
                        size = 0 if is_dir else item.stat(follow_symlinks=False).st_size
                    except OSError:
                        is_dir, is_link, size = False, False, 0
                    entry: dict[str, Any] = {
                        "name": item.name,
                        "path": item.path,
                        "type": "dir" if is_dir else ("symlink" if is_link else "file"),
                    }
                    if not is_dir:
                        entry["bytes"] = size
                    entries.append(entry)
                    if is_dir and level + 1 < depth:
                        frontier.append((item.path, level + 1))
        except OSError as exc:
            raise PeerError("sandbox_denied", f"cannot list {current!r}: {exc.strerror}") from None
    return entries, truncated
