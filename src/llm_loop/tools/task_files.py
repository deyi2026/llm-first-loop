"""Task Lease fenced FileService adapter for exact cross-project edits.

Not a model-facing tool. The trusted runtime must inject the signed Host
context, per-project durable FileEffectSink and FileService with an audit-root
lock directory. A lease never overrides parent scope or another Lane.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

from llm_loop.tools.task_execution import TaskExecutionError, TrustedTaskExecution
from llm_loop.workspace.file_effects import FileEffectSink
from llm_loop.workspace.file_service import FileEditResult, FileService


class TaskFileError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _FencedFileSink:
    """Delegate WAL to caller; recheck Host lease at the physical write fence."""

    def __init__(self, inner: FileEffectSink, task: TrustedTaskExecution, target: str) -> None:
        self._inner = inner
        self._task = task
        self._target = target
        self.workspace_scope = inner.workspace_scope
        self.owner_session_id = inner.owner_session_id
        self.operation_id = inner.operation_id
        self.tool_call_id = inner.tool_call_id
        self.tool_name = inner.tool_name
        self.effect_kind = inner.effect_kind

    @property
    def records_durable(self) -> bool:
        return self._inner.records_durable

    def prepared(
        self, *, canonical_path: Path, before_bytes: bytes, expected_after_bytes: bytes
    ) -> bool:
        return self._inner.prepared(
            canonical_path=canonical_path,
            before_bytes=before_bytes,
            expected_after_bytes=expected_after_bytes,
        )

    def observed(
        self,
        *,
        canonical_path: Path,
        actual_after_bytes: bytes,
        expected_after_bytes: bytes,
        actual_mtime_ns: int | None,
        artifact_ref: str,
    ) -> bool:
        return self._inner.observed(
            canonical_path=canonical_path,
            actual_after_bytes=actual_after_bytes,
            expected_after_bytes=expected_after_bytes,
            actual_mtime_ns=actual_mtime_ns,
            artifact_ref=artifact_ref,
        )

    @contextmanager
    def mutation_authority(self) -> Iterator[object]:
        factory = getattr(self._inner, "mutation_authority", None)
        context = cast(
            contextlib.AbstractContextManager[object],
            factory() if callable(factory) else contextlib.nullcontext(True),
        )
        with context as allowed:
            if not allowed:
                yield allowed
            else:
                self._task.authorize_file(self._target, "write")
                yield True


class TaskFileAdapter:
    def __init__(self, *, task: TrustedTaskExecution, service: FileService) -> None:
        self._task = task
        self._service = service

    def edit_existing(
        self,
        *,
        path: str,
        old_string: str,
        new_string: str,
        expected_sha256: str,
        effect_sink: FileEffectSink,
        replace_all: bool = False,
    ) -> FileEditResult:
        if (
            not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in expected_sha256)
        ):
            raise TaskFileError("task_file_version_precondition_required")
        if effect_sink is None or not effect_sink.records_durable:
            raise TaskFileError("task_file_durable_effect_sink_required")
        target = os.path.abspath(path)
        if target != path or os.path.realpath(target) != target:
            raise TaskFileError("task_file_path_not_canonical")
        lock_root = self._service._lock_root
        if lock_root is None or not any(
            os.path.commonpath((str(lock_root), os.path.realpath(root))) == os.path.realpath(root)
            for root in self._task.protected_roots
        ):
            raise TaskFileError("task_file_lock_root_untrusted")
        try:
            root = self._task.authorize_file(target, "write")
            if (
                os.path.realpath(effect_sink.workspace_scope) != root
                or effect_sink.owner_session_id != self._task.owner_session_id
            ):
                raise TaskFileError("task_file_sink_identity_mismatch")
            fenced = _FencedFileSink(effect_sink, self._task, target)
            return self._service.edit(
                path=Path(target),
                old_string=old_string,
                new_string=new_string,
                replace_all=replace_all,
                dry_run=False,
                expected_sha256=expected_sha256,
                workspace_scope=root,
                effect_sink=cast(FileEffectSink, fenced),
            )
        except TaskExecutionError as exc:
            raise TaskFileError(exc.reason_code) from exc
