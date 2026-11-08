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
- ``fs.write`` 执行器已就绪，但**宣告面未开**：``kinds.EXECUTABLE_KINDS`` 仍只有只读两种，
  manifest 不对外声称可写；准入侧 ``supervised`` 仍硬编码 False，故线上 fs.write 一律
  ``requires_supervised_execution``。"有人在场通道 + 宣告"属 T9-b，与契约修复同批落地。
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
        target = require_write_target(params["path"], write_root=self._write_root)
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

        self._atomic_write(target, payload)
        digest = hashlib.sha256(payload).hexdigest()
        return ExecOutcome(summary=f"wrote {len(payload)} bytes to {target} (sha256={digest})")

    # --- helpers ------------------------------------------------------------
    def _write_payload(self, params: dict[str, Any]) -> bytes:
        """内容源二选一由闸3 ``validate_params`` 保证；这里只解，不再兜底。"""
        if "content_b64" in params:
            try:
                return base64.b64decode(params["content_b64"], validate=True)
            except (binascii.Error, ValueError):
                raise PeerError("params_schema_invalid", "content_b64 is not valid base64") from None
        return self._artifacts.read(params["artifact_ref"])

    @staticmethod
    def _atomic_write(target: str, payload: bytes) -> None:
        """同目录临时文件 + ``os.replace``；跨设备/无权限映射为可判定错误码。"""
        parent = os.path.dirname(target)
        try:
            fd, tmp = tempfile.mkstemp(dir=parent, prefix=".lfl-peer-write-")
        except OSError as exc:
            raise PeerError("sandbox_denied", f"cannot create temp file: {exc.strerror}") from None
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o644)
            os.replace(tmp, target)
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
