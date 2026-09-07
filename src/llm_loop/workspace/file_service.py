"""Shared exact-byte file service for coordinated workspace operations.

This service owns only mechanical file facts: observation, byte identity, path-scoped
coordination, version preconditions, deterministic text replacement, atomic replace,
post-write verification and immutable artifact snapshots. It never interprets task
semantics, user intent, evidence sufficiency, retry desirability or completion.
"""

from __future__ import annotations

import contextlib
import difflib
import hashlib
import os
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from llm_loop.workspace.artifacts import ArtifactError, WorkspaceArtifactStore
from llm_loop.workspace.file_effects import FileArtifactProvenance, FileEffectSink

DIFF_MAX_LINES = 80
UTF8_BOM = b"\xef\xbb\xbf"
FILE_CONTRACT_VERSION = 1

_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}


def detect_line_ending(text: str) -> str:
    """Return CRLF when it is the dominant original newline style, otherwise LF."""
    crlf = text.count("\r\n")
    lf_only = text.count("\n") - crlf
    return "\r\n" if crlf > lf_only else "\n"


def normalize_lf(text: str) -> str:
    """Normalize CRLF/CR to LF for content matching only."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


@dataclass(frozen=True, slots=True)
class FileObservation:
    path: str
    snapshot_ref: str
    sha256: str
    size_bytes: int
    observed_at: float
    content_range: tuple[int, int]
    content: str
    total_lines: int
    workspace_path_state: str
    source_version_token: str | None = None
    file_contract_version: int = FILE_CONTRACT_VERSION


@dataclass(frozen=True, slots=True)
class FileEditResult:
    path: Path
    source_bytes: bytes
    expected_after_bytes: bytes
    actual_after_bytes: bytes | None
    baseline_before: tuple[int, int]
    post_baseline: tuple[int, int] | None
    match_count: int
    diff_text: str
    full_diff_text: str
    added_lines: int
    removed_lines: int
    had_bom: bool
    line_ending: str
    dry_run: bool
    applied: bool
    artifact_fact: dict[str, object] | None = None
    artifact_error_type: str = ""
    expected_snapshot_ref: str = ""
    precondition_checked: bool = False
    receipt_state: str = "unknown"
    file_contract_version: int = FILE_CONTRACT_VERSION


class FileServiceError(ValueError):
    """Mechanical file-operation failure with a stable adapter-facing reason."""

    def __init__(
        self,
        error_type: str,
        *,
        detail: str = "",
        cause_type: str = "",
        match_count: int = 0,
    ) -> None:
        self.error_type = error_type
        self.detail = detail
        self.cause_type = cause_type
        self.match_count = match_count
        super().__init__(detail or error_type)


def _process_lock(key: str) -> threading.RLock:
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, threading.RLock())


class FileService:
    """Exact-byte single-file core shared by coordinated writers/read snapshots."""

    def __init__(
        self,
        *,
        artifact_store: WorkspaceArtifactStore | None = None,
        baseline_reader: Callable[[Path], tuple[int, int]] | None = None,
        lock_root: str | Path | None = None,
    ) -> None:
        self.artifact_store = artifact_store
        self._baseline_reader = baseline_reader or self.baseline
        if lock_root is not None:
            self._lock_root: Path | None = Path(lock_root).expanduser().resolve()
        elif artifact_store is not None:
            self._lock_root = artifact_store.root.parent / "file_locks"
        else:
            self._lock_root = None

    @staticmethod
    def baseline(path: Path) -> tuple[int, int]:
        st = path.stat()
        return st.st_mtime_ns, st.st_size

    @staticmethod
    def _canonical_scope(workspace_scope: str | Path) -> Path:
        return Path(workspace_scope).expanduser().resolve()

    @staticmethod
    def _relative_to_scope(path: Path, workspace_scope: str | Path) -> str:
        scope = FileService._canonical_scope(workspace_scope)
        target = path.expanduser().resolve()
        try:
            return target.relative_to(scope).as_posix()
        except ValueError as exc:
            raise FileServiceError("WorkspaceScopeMismatch") from exc

    def _lock_key(self, path: Path, workspace_scope: str | None) -> str:
        target = str(path.expanduser().resolve())
        scope = (
            str(self._canonical_scope(workspace_scope))
            if workspace_scope
            else str(path.expanduser().resolve().parent)
        )
        return hashlib.sha256(f"{scope}\0{target}".encode()).hexdigest()

    @contextmanager
    def _path_lock(self, path: Path, workspace_scope: str | None = None) -> Iterator[None]:
        """Stable workspace+path lock; target inode is never used as the lock object."""
        key = self._lock_key(path, workspace_scope)
        process_lock = _process_lock(key)
        with process_lock:
            if self._lock_root is None:
                yield
                return
            lock_path = self._lock_root / key[:2] / f"{key}.lock"
            try:
                lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                lock_file = lock_path.open("a", encoding="utf-8")
            except OSError as exc:
                raise FileServiceError(
                    "PathLockUnavailable", detail=str(exc), cause_type=type(exc).__name__
                ) from exc
            try:
                try:
                    import fcntl
                except ImportError:
                    # Current qualification targets macOS/Linux. The process lock still
                    # preserves same-process correctness where flock is unavailable.
                    yield
                    return
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                except OSError as exc:
                    raise FileServiceError(
                        "PathLockUnavailable", detail=str(exc), cause_type=type(exc).__name__
                    ) from exc
                try:
                    yield
                finally:
                    with contextlib.suppress(OSError):
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()

    def observe(
        self,
        *,
        path: Path,
        workspace_scope: str,
        provenance: FileArtifactProvenance,
        offset: int = 0,
        limit: int | None = None,
        max_bytes: int | None = None,
        strict_utf8: bool = False,
        strip_utf8_bom: bool = False,
    ) -> FileObservation:
        """Physically read current full bytes and materialize one immutable baseline."""
        if self.artifact_store is None:
            raise FileServiceError("SnapshotUnavailable")
        scope = str(self._canonical_scope(workspace_scope))
        relative = self._relative_to_scope(path, scope)
        if str(self._canonical_scope(provenance.workspace_scope)) != scope:
            raise FileServiceError("WorkspaceScopeMismatch")
        source_version_token: str | None = None
        with self._path_lock(path, scope):
            try:
                stat_before = path.stat()
                byte_limit = max(0, int(max_bytes)) if max_bytes is not None else None
                if byte_limit is not None and stat_before.st_size > byte_limit:
                    raise FileServiceError("ResourceLimitExceeded")
                data = path.read_bytes()
                # Re-check actual bytes in case the file grew after stat_before.
                if byte_limit is not None and len(data) > byte_limit:
                    raise FileServiceError("ResourceLimitExceeded")
                if strict_utf8:
                    probe = data[len(UTF8_BOM) :] if data.startswith(UTF8_BOM) else data
                    try:
                        probe.decode("utf-8")
                    except UnicodeDecodeError as exc:
                        raise FileServiceError("UnsupportedTextEncoding", detail=str(exc)) from exc
                stat_after = path.stat()
                if (stat_before.st_mtime_ns, stat_before.st_size) == (
                    stat_after.st_mtime_ns, stat_after.st_size
                ):
                    source_version_token = (
                        f"stat:{stat_after.st_mtime_ns}:{stat_after.st_size}"
                    )
            except FileServiceError:
                raise
            except FileNotFoundError as exc:
                raise FileServiceError("FileNotFoundError") from exc
            except OSError as exc:
                raise FileServiceError(
                    "ReadError", detail=str(exc), cause_type=type(exc).__name__
                ) from exc
            try:
                record = self.artifact_store.create(
                    workspace_scope=scope,
                    canonical_path=str(path),
                    data=data,
                    owner_session_id=provenance.owner_session_id,
                    execution_id=provenance.operation_id,
                    tool_call_id=provenance.tool_call_id,
                    tool_name=provenance.tool_name,
                    effect_kind=provenance.effect_kind,
                )
                resolution = self.artifact_store.snapshot(record.ref, workspace_scope=scope)
            except ArtifactError as exc:
                raise FileServiceError("SnapshotUnavailable", detail=str(exc)) from exc

        visible_data = data[len(UTF8_BOM) :] if strip_utf8_bom and data.startswith(UTF8_BOM) else data
        text = visible_data.decode("utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        total = len(lines)
        start = max(0, min(int(offset or 0), total))
        selected = lines[start:]
        if limit is not None:
            selected = selected[: max(0, int(limit))]
        end = start + len(selected)
        return FileObservation(
            path=relative,
            snapshot_ref=record.ref,
            sha256=record.sha256,
            size_bytes=record.size_bytes,
            observed_at=record.created_at,
            content_range=(start, end),
            content="".join(selected),
            total_lines=total,
            workspace_path_state=resolution.workspace_path_state,
            source_version_token=source_version_token,
        )

    def edit(
        self,
        *,
        path: Path,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
        dry_run: bool = False,
        effect_sink: FileEffectSink | None = None,
        workspace_scope: str | None = None,
        expected_snapshot_ref: str = "",
        whole_file: bool = False,
    ) -> FileEditResult:
        """Coordinate one exact-byte edit under a stable path lock."""
        with self._path_lock(path, workspace_scope):
            return self._edit_locked(
                path=path,
                old_string=old_string,
                new_string=new_string,
                replace_all=replace_all,
                dry_run=dry_run,
                effect_sink=effect_sink,
                workspace_scope=workspace_scope,
                expected_snapshot_ref=str(expected_snapshot_ref or ""),
                whole_file=whole_file,
            )

    def _edit_locked(
        self,
        *,
        path: Path,
        old_string: str,
        new_string: str,
        replace_all: bool,
        dry_run: bool,
        effect_sink: FileEffectSink | None,
        workspace_scope: str | None,
        expected_snapshot_ref: str,
        whole_file: bool,
    ) -> FileEditResult:
        try:
            raw = path.read_bytes()
            source_bytes = raw
        except FileNotFoundError as exc:
            raise FileServiceError("FileNotFoundError") from exc
        except OSError as exc:
            raise FileServiceError(
                "ReadError", detail=str(exc), cause_type=type(exc).__name__
            ) from exc

        try:
            baseline = self._baseline_reader(path)
        except OSError as exc:
            raise FileServiceError(
                "BaselineSnapshotFailed", detail=str(exc), cause_type=type(exc).__name__
            ) from exc

        precondition_checked = False
        if expected_snapshot_ref:
            if self.artifact_store is None or not workspace_scope:
                raise FileServiceError("VersionPreconditionInvalid")
            scope = str(self._canonical_scope(workspace_scope))
            relative = self._relative_to_scope(path, scope)
            try:
                resolution, expected_bytes = self.artifact_store.hydrate(
                    expected_snapshot_ref, workspace_scope=scope
                )
            except ArtifactError as exc:
                raise FileServiceError("VersionPreconditionInvalid", detail=str(exc)) from exc
            if resolution.record.relative_path != relative:
                raise FileServiceError("VersionPreconditionInvalid")
            precondition_checked = True
            if source_bytes != expected_bytes:
                raise FileServiceError("VersionConflict")

        had_bom = raw.startswith(UTF8_BOM)
        if had_bom:
            raw = raw[len(UTF8_BOM) :]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FileServiceError("UnicodeDecodeError", detail=str(exc)) from exc

        ending = detect_line_ending(text)
        original = normalize_lf(text)
        old_n = normalize_lf(old_string)
        new_n = normalize_lf(new_string)
        if whole_file:
            count = 1
            updated = new_n
        else:
            count = original.count(old_n)
            if count == 0:
                raise FileServiceError("NoMatch")
            if count > 1 and not replace_all:
                raise FileServiceError("MultipleMatches", match_count=count)
            updated = original.replace(old_n, new_n)
        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(),
                updated.splitlines(),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
                lineterm="",
                n=2,
            )
        )
        full_diff_text = "\n".join(diff_lines)
        diff_text = "\n".join(diff_lines[:DIFF_MAX_LINES])
        if len(diff_lines) > DIFF_MAX_LINES:
            diff_text += (
                f"\n... [diff 过长已截断: 共 {len(diff_lines)} 行，"
                f"显示前 {DIFF_MAX_LINES} 行]"
            )
        added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

        out_text = updated if ending == "\n" else updated.replace("\n", ending)
        out_bytes = (UTF8_BOM if had_bom else b"") + out_text.encode("utf-8")
        if dry_run:
            return FileEditResult(
                path=path,
                source_bytes=source_bytes,
                expected_after_bytes=out_bytes,
                actual_after_bytes=None,
                baseline_before=baseline,
                post_baseline=None,
                match_count=count,
                diff_text=diff_text,
                full_diff_text=full_diff_text,
                added_lines=added,
                removed_lines=removed,
                had_bom=had_bom,
                line_ending=ending,
                dry_run=True,
                applied=False,
                expected_snapshot_ref=expected_snapshot_ref,
                precondition_checked=precondition_checked,
            )

        try:
            if self._baseline_reader(path) != baseline:
                raise FileServiceError("BaselineChanged")
            # mtime/size is a legacy race detector, not a version proof. Re-read exact
            # bytes before mutation so same-size/same-mtime changes are not ignored.
            if path.read_bytes() != source_bytes:
                raise FileServiceError("BaselineChanged")
        except FileServiceError:
            raise
        except OSError as exc:
            raise FileServiceError(
                "BaselineCheckFailed", detail=str(exc), cause_type=type(exc).__name__
            ) from exc

        if effect_sink is not None:
            prepared = effect_sink.prepared(
                canonical_path=path,
                before_bytes=source_bytes,
                expected_after_bytes=out_bytes,
            )
            if not prepared:
                raise FileServiceError("EffectPreparedUnavailable")

        try:
            fd, tmp_name = tempfile.mkstemp(
                dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
            )
            tmp = Path(tmp_name)
            try:
                with os.fdopen(fd, "wb") as file_obj:
                    file_obj.write(out_bytes)
                    file_obj.flush()
                    os.fsync(file_obj.fileno())
                os.replace(tmp, path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp)
                raise
        except OSError as exc:
            raise FileServiceError(
                "WriteFailed", detail=str(exc), cause_type=type(exc).__name__
            ) from exc

        try:
            reread = path.read_bytes()
        except OSError as exc:
            raise FileServiceError(
                "VerifyReadFailed", detail=str(exc), cause_type=type(exc).__name__
            ) from exc
        if reread != out_bytes:
            raise FileServiceError("VerifyMismatch")

        post_stat = path.stat()
        artifact_fact: dict[str, object] | None = None
        artifact_error_type = ""
        if (
            effect_sink is not None
            and effect_sink.records_durable
            and self.artifact_store is not None
        ):
            try:
                artifact = self.artifact_store.create(
                    workspace_scope=effect_sink.workspace_scope,
                    canonical_path=str(path),
                    data=reread,
                    owner_session_id=effect_sink.owner_session_id,
                    execution_id=effect_sink.operation_id,
                    tool_call_id=effect_sink.tool_call_id,
                    tool_name=effect_sink.tool_name,
                    effect_kind=effect_sink.effect_kind,
                )
                artifact_fact = artifact.public_facts()
            except Exception as exc:  # noqa: BLE001 - successful bytes stay authoritative
                artifact_error_type = type(exc).__name__

        receipt_state = "unknown"
        if effect_sink is not None:
            observed_recorded = effect_sink.observed(
                canonical_path=path,
                actual_after_bytes=reread,
                expected_after_bytes=out_bytes,
                actual_mtime_ns=post_stat.st_mtime_ns,
                artifact_ref=(
                    str(artifact_fact.get("artifact_ref") or "")
                    if artifact_fact is not None
                    else ""
                ),
            )
            receipt_state = "recorded" if observed_recorded else "recording_failed"
        if artifact_error_type:
            receipt_state = "recording_failed"

        return FileEditResult(
            path=path,
            source_bytes=source_bytes,
            expected_after_bytes=out_bytes,
            actual_after_bytes=reread,
            baseline_before=baseline,
            post_baseline=(post_stat.st_mtime_ns, post_stat.st_size),
            match_count=count,
            diff_text=diff_text,
            full_diff_text=full_diff_text,
            added_lines=added,
            removed_lines=removed,
            had_bom=had_bom,
            line_ending=ending,
            dry_run=False,
            applied=True,
            artifact_fact=artifact_fact,
            artifact_error_type=artifact_error_type,
            expected_snapshot_ref=expected_snapshot_ref,
            precondition_checked=precondition_checked,
            receipt_state=receipt_state,
        )
