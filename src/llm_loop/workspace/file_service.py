"""Shared exact-byte file service for coordinated workspace operations.

This service owns only mechanical file facts: observation, byte identity, path-scoped
coordination, version preconditions, deterministic text replacement, atomic replace,
post-write verification and immutable artifact snapshots. It never interprets task
semantics, user intent, evidence sufficiency, retry desirability or completion.

Write-scope enforcement (DESIGN-20261030 §5.3 C6): ``edit()`` and ``observe()`` accept
an optional ``write_scope`` (default ``None`` = unscoped = legacy behavior byte-for-byte,
FR-3/§5.10). DECISION, made explicit per the C6 mandate: **the scope constrains reads
and writes uniformly at this service level (fail-closed)**. Rationale:

1. ``observe()`` materializes full-content immutable snapshots; letting a scoped
   execution domain snapshot bytes outside its declared paths would move file content
   across the very ownership boundary the scope declares.
2. One uniform judgment (the pinned ``scope_allows``) avoids two subtly divergent
   read/write policies drifting apart at the same choke point.

FR-4's "``paths: []`` = read-only subagent" is preserved where it is actually wired:
the design's C-list wires only ``edit_file`` (C7) to pass the scope, so a
``paths: []`` child still reads via read_file (read tools pass no scope) while every
write is deterministically rejected. Direct API callers that *do* pass a scope to
``observe()`` get read enforcement too — deliberate, documented here, not accidental.
For ``edit()`` an empty allow set means no path is writable, so ``paths: []`` is
always rejected; for ``observe()`` with an explicitly passed empty-allow scope the
read is likewise rejected (same fail-closed reading).
"""

from __future__ import annotations

import contextlib
import difflib
import hashlib
import os
import tempfile
import threading
import weakref
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from llm_loop.workspace.artifacts import ArtifactError, WorkspaceArtifactStore
from llm_loop.workspace.file_effects import FileArtifactProvenance, FileEffectSink

if TYPE_CHECKING:
    # Annotation-only import: the enforcement module is consumed lazily at runtime
    # (see _write_scope_api) so unscoped legacy callers never import it.
    from llm_loop.core.write_scope import WriteScope

DIFF_MAX_LINES = 80
UTF8_BOM = b"\xef\xbb\xbf"
FILE_CONTRACT_VERSION = 1

# §5.5/NFR-3: rejection receipts list allow patterns capped at this many entries,
# with the total count noted when truncated. Never file content, never a stack.
WRITE_SCOPE_PATTERN_PREVIEW_LIMIT = 10

_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: weakref.WeakValueDictionary[str, threading.RLock] = weakref.WeakValueDictionary()


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


_write_scope_api_cache: tuple[Any, Any, Any] | None = None


def _write_scope_api() -> tuple[Any, Any, Any]:
    """Resolve the pinned ``llm_loop.core.write_scope`` hooks lazily, once.

    ``core/write_scope.py`` is a parallel workstream of the write-scope design
    (§5.3). Resolving lazily keeps every legacy call site (``write_scope=None``)
    import-cost- and behavior-identical while that module lands; scoped calls
    resolve the module exactly once and reuse it. There is deliberately no
    fallback shim: a missing or divergent core module surfaces as a loud
    ImportError on the enforcement path, never as silent fail-open.
    """
    global _write_scope_api_cache
    if _write_scope_api_cache is None:
        from llm_loop.core import write_scope as _ws

        _write_scope_api_cache = (
            _ws.scope_allows,
            _ws.write_scope_audit_record_violation,
            _ws.write_scope_audit_record_write,
        )
    return _write_scope_api_cache


def _format_pattern_list(label: str, items: Any) -> str:
    """One bounded pattern listing for receipts: capped at the preview limit."""
    entries = sorted(str(item) for item in items)
    total = len(entries)
    if total == 0:
        if label.startswith("allow"):
            return f"{label}: （空集合 = 只读执行域，无任何路径被允许）"
        return f"{label}: （空集合）"
    head = ", ".join(entries[:WRITE_SCOPE_PATTERN_PREVIEW_LIMIT])
    if total > WRITE_SCOPE_PATTERN_PREVIEW_LIMIT:
        return f"{label}（共 {total} 条，仅显示前 {WRITE_SCOPE_PATTERN_PREVIEW_LIMIT} 条）: {head}"
    return f"{label}（共 {total} 条）: {head}"


def _write_scope_pattern_preview(write_scope: Any) -> str:
    """Mode-aware, bounded pattern listing for rejection receipts (§5.5).

    The pinned contract exposes *behavior* via ``scope_allows``; the pattern set
    for receipts is read from the delivered dataclass shape (``paths``/``mode``/
    ``deny_paths``). ``mode`` matters: in deny mode ``paths`` is the exclusion
    set, so it must never be labeled "allow". An unknown object shape degrades
    to an honest placeholder rather than an unbounded repr dump.
    """
    mode = getattr(write_scope, "mode", None)
    pattern_set: Any = None
    for attr in ("paths", "allow", "allow_paths", "allow_patterns"):
        value = getattr(write_scope, attr, None)
        if isinstance(value, (list, tuple, frozenset, set)):
            pattern_set = value
            break
    parts: list[str] = []
    if pattern_set is None:
        parts.append(
            "patterns: （当前 scope 对象未暴露可枚举 pattern 字段，类型 "
            f"{type(write_scope).__name__}）"
        )
    elif mode == "deny":
        parts.append(_format_pattern_list("deny patterns（deny 模式，命中即拒）", pattern_set))
    else:
        parts.append(_format_pattern_list("allow patterns", pattern_set))
    deny_extra = getattr(write_scope, "deny_paths", None)
    if isinstance(deny_extra, (list, tuple, frozenset, set)) and len(deny_extra) > 0:
        parts.append(_format_pattern_list("deny patterns（叠加，优先于 allow）", deny_extra))
    return " ".join(parts)


_WRITE_SCOPE_ADVICE: dict[str, str] = {
    "outside_scope": (
        "目标路径在声明的写范围根之外；请改写到允许范围内的路径，"
        "或由父会话在派发时扩大 write_scope.paths 声明（运行期声明不构成授权）。"
    ),
    "not_in_allow_list": (
        "目标路径未被任何 allow pattern 覆盖；请核对上方 pattern 集合后改用范围内路径，"
        "或由父会话修正声明后重新派发。"
    ),
    "denied_by_deny_list": (
        "目标路径命中 deny 清单（deny 优先于 allow）；如确需写入须由父会话调整 deny "
        "声明，子执行域内无法自行解锁。"
    ),
}


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

    def _enforce_write_scope(
        self,
        *,
        write_scope: WriteScope | None,
        path: Path,
        workspace_scope: str,
        operation: str,
    ) -> None:
        """C6 write-scope gate: deterministic judgment before any durable side effect.

        Called only after workspace canonicalization and strictly before locks,
        reads-of-record, snapshot materialization or mutation — a rejection here
        leaves the target file's bytes untouched and creates no half-products
        (FR-5/NFR-5). ``write_scope=None`` (unscoped parent) skips the gate so
        legacy callers keep byte-identical behavior and never import the core
        module. The judgment itself is delegated to the pinned ``scope_allows``,
        which owns path normalization (realpath: symlink escapes and ``..``
        traversal per FR-6/FR-7) and allow/deny glob matching relative to
        ``workspace_root``; this method adds no git calls and no IO of its own
        beyond that (NFR-1).
        """
        if write_scope is None:
            return
        scope_allows, record_violation, _record_write = _write_scope_api()
        target = str(path.expanduser())
        allowed, reason = scope_allows(write_scope, target, workspace_scope)
        if allowed:
            return
        # Forensic audit is best-effort: the deterministic rejection itself is
        # the enforcement and must not be replaceable by an audit failure.
        with contextlib.suppress(Exception):  # noqa: BLE001
            record_violation(target, reason)
        advice = _WRITE_SCOPE_ADVICE.get(
            reason, f"拒绝类别 {reason or 'unknown'}；请核对 write_scope 声明后改用范围内路径。"
        )
        raise FileServiceError(
            "write_scope_violation",
            detail=(
                f"[{operation}] 目标路径 {target} 不在本执行域被允许的范围内，已拒绝"
                "（本次未产生任何写入/快照副作用）。"
                f"拒绝类别: {reason or 'unknown'}。"
                f"{_write_scope_pattern_preview(write_scope)}。"
                f"修正建议: {advice}"
            ),
        )

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
        write_scope: WriteScope | None = None,
    ) -> FileObservation:
        """Physically read current full bytes and materialize one immutable baseline."""
        if self.artifact_store is None:
            raise FileServiceError("SnapshotUnavailable")
        scope = str(self._canonical_scope(workspace_scope))
        relative = self._relative_to_scope(path, scope)
        if str(self._canonical_scope(provenance.workspace_scope)) != scope:
            raise FileServiceError("WorkspaceScopeMismatch")
        # C6: the same scope constrains reads here (uniform read/write fail-closed
        # decision documented in the module docstring). Enforced before the path
        # lock and before any bytes are read, so an out-of-scope observe leaves
        # no snapshot and touches nothing.
        self._enforce_write_scope(
            write_scope=write_scope,
            path=path,
            workspace_scope=scope,
            operation="observe",
        )
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
        write_scope: WriteScope | None = None,
    ) -> FileEditResult:
        """Coordinate one exact-byte edit under a stable path lock."""
        if write_scope is not None:
            # C6: scoped writes require an explicit workspace root (patterns are
            # matched relative to it). This precondition failure is a caller
            # contract error, surfaced through the existing E5 error family.
            if not workspace_scope:
                raise FileServiceError(
                    "WorkspaceScopeMismatch",
                    detail="write_scope enforcement requires an explicit workspace_scope",
                )
            # Gate strictly before the path lock and before any read of record:
            # a rejection creates no lock file, no temp file, no byte change.
            self._enforce_write_scope(
                write_scope=write_scope,
                path=path,
                workspace_scope=str(self._canonical_scope(workspace_scope)),
                operation="edit",
            )
        with self._path_lock(path, workspace_scope):
            result = self._edit_locked(
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
        if write_scope is not None and result.applied:
            # C6/§5.7: forensic record after a successfully verified durable write
            # (dry_run never lands bytes, so it is never recorded). Best-effort:
            # the WAL/artifact receipt already carries the authoritative write
            # fact; an audit-infrastructure failure must not turn an already
            # committed write into a reported failure.
            _scope_allows, _record_violation, record_write = _write_scope_api()
            with contextlib.suppress(Exception):  # noqa: BLE001 - forensic audit is best-effort
                record_write(str(path.expanduser()))
        return result

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

        authority_factory = (
            getattr(effect_sink, "mutation_authority", None) if effect_sink is not None else None
        )
        authority_ctx: contextlib.AbstractContextManager = contextlib.nullcontext(True)
        if callable(authority_factory):
            authority_ctx = cast(contextlib.AbstractContextManager, authority_factory())
        with authority_ctx as mutation_allowed:
            if not mutation_allowed:
                # EVO-20261014-459a8a1e: 真实层（E3 lease / E4 代际）线程化到异常 detail，
                # 上层 unauthorized 回执与 exception_log 均可按层统计。
                fence_code = str(getattr(mutation_allowed, "code", "") or "")
                fence_reason = str(getattr(mutation_allowed, "reason", "") or "")
                fence_facts = getattr(mutation_allowed, "facts", None) or {}
                facts_txt = " ".join(
                    f"{k}={v}" for k, v in sorted(dict(fence_facts).items())
                )
                detail = " | ".join(
                    part
                    for part in (
                        f"[{fence_code}]" if fence_code else "",
                        fence_reason,
                        f"facts: {facts_txt}" if facts_txt else "",
                    )
                    if part
                )
                raise FileServiceError("EffectAuthorityLost", detail=detail)
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
