"""任务执行器（受控端）：首切片只实现只读的 ``fs.read`` / ``fs.list``。

设计约束（DESIGN §5.4/§5.5）：
- 闸3（policy）已判定 kind/租约/路径；执行器**再解析一次** realpath 并用
  ``O_NOFOLLOW`` 打开，把"策略判定的路径"与"实际读的路径"绑成同一个，
  减小 TOCTOU 窗口（残余：realpath 与实际 inode 之间的窗口仍存在，故仍依赖闸4）。
- 产物不内联：内容一律进 ArtifactStore，回执只带 ``artifact://v1/<sha256>``。
- 未实现的 kind 明确拒绝（``policy_task_kind_not_allowed`` + detail ``handler_missing``），
  不假装成功、不返回空结果。

首切片未实现（下一轮）：``fs.write`` / ``shell.exec`` / ``desktop.*``（需要闸4 写侧
或 X11 采集，属有人在场路径）。
"""

from __future__ import annotations

import errno
import json
import os
from dataclasses import dataclass, field
from typing import Any

from .artifacts import ArtifactStore
from .errors import PeerError
from .policy import DEFAULT_MAX_READ_BYTES, require_path_allowed

MAX_LIST_ENTRIES = 500


@dataclass(frozen=True)
class ExecOutcome:
    summary: str
    artifacts: tuple[dict[str, Any], ...] = field(default_factory=tuple)


class Executor:
    def __init__(self, *, artifacts: ArtifactStore, node_id: str) -> None:
        self._artifacts = artifacts
        self._node_id = node_id

    def run(
        self,
        *,
        kind: str,
        params: dict[str, Any],
        allowed_paths: tuple[str, ...],
    ) -> ExecOutcome:
        handler = getattr(self, "_run_" + kind.replace(".", "_"), None)
        if handler is None:
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

    # --- helpers ------------------------------------------------------------
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
