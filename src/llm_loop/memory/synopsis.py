"""Durable model-authored synopses bound to exact source snapshots.

A synopsis is a derived navigation view, never a replacement for its source.  The
program owns only mechanical identity, scope, integrity and resource checks; the model
owns the summary text and any judgement about what it means for the current task.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

SYNOPSIS_SCHEME = "synopsis:"
SYNOPSIS_VERSION = 1
MAX_SYNOPSIS_CHARS = 32_000
MAX_SOURCE_SNAPSHOT_CHARS = 16_000_000
MAX_SOURCE_READ_CHARS = 95_000

AccessScope = Literal["workspace", "session"]


class SynopsisError(ValueError):
    """A synopsis/source request cannot be satisfied without guessing."""


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """One exact, mechanically resolved model-readable source representation."""

    source_ref: str
    source_kind: str
    text: str
    source_sha256: str
    source_chars: int
    source_complete: bool
    representation: str
    access_scope: AccessScope
    origin_sha256: str = ""

    def __post_init__(self) -> None:
        if self.access_scope not in {"workspace", "session"}:
            raise ValueError("invalid source access_scope")
        if self.source_chars != len(self.text):
            raise ValueError("source_chars mismatch")
        digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.source_sha256 != digest:
            raise ValueError("source_sha256 mismatch")


@dataclass(frozen=True, slots=True)
class SynopsisRecord:
    version: int
    synopsis_id: str
    ref: str
    workspace_scope: str
    session_id: str
    access_scope: AccessScope
    source_access_scope: AccessScope
    source_ref: str
    source_kind: str
    source_sha256: str
    source_chars: int
    source_complete: bool
    source_representation: str
    origin_sha256: str
    source_start: int
    source_end: int
    range_sha256: str
    range_chars: int
    summary: str
    summary_sha256: str
    summary_chars: int
    summary_model: str
    created_at: float
    representation: str = "model_authored_synopsis"
    task_applicability: str = "not_evaluated"

    def public_card(self, *, source_ref_state: str = "not_checked") -> dict[str, Any]:
        return {
            "kind": "synopsis",
            "id": self.ref,
            "ref": self.ref,
            "ts": self.created_at,
            "summary": " ".join(self.summary.split())[:300],
            "source_ref": self.source_ref,
            "source_kind": self.source_kind,
            "source_access_scope": self.source_access_scope,
            "source_sha256": self.source_sha256,
            "source_chars": self.source_chars,
            "source_complete": self.source_complete,
            "snapshot_complete": True,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "range_sha256": self.range_sha256,
            "summary_model": self.summary_model,
            "representation": self.representation,
            "projection_complete": False,
            "source_ref_state": source_ref_state,
            "task_applicability": self.task_applicability,
        }

    def hydrated(self, *, source_ref_state: str = "not_checked") -> dict[str, Any]:
        data = self.public_card(source_ref_state=source_ref_state)
        data.update(
            {
                "summary": self.summary,
                "summary_sha256": self.summary_sha256,
                "summary_chars": self.summary_chars,
                "source_representation": self.source_representation,
                "origin_sha256": self.origin_sha256,
                "projection_complete": True,
                "coverage_semantics": "model_declared_source_range_not_semantically_verified",
            }
        )
        return data


def _canonical_scope(root: str | Path | None) -> str:
    raw = Path(root).expanduser() if root else Path.cwd()
    return str(raw.resolve())


def _workspace_bucket(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:32]


def _synopsis_id(ref: str) -> str:
    if not isinstance(ref, str) or not ref.startswith(SYNOPSIS_SCHEME):
        raise SynopsisError("synopsis 引用格式无效。")
    value = ref[len(SYNOPSIS_SCHEME) :]
    if len(value) != 32:
        raise SynopsisError("synopsis 引用格式无效。")
    try:
        int(value, 16)
    except ValueError as exc:
        raise SynopsisError("synopsis 引用格式无效。") from exc
    return value


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        with suppress(OSError):
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        with suppress(OSError):
            os.chmod(path, 0o600)
    finally:
        with suppress(OSError):
            tmp.unlink(missing_ok=True)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    _atomic_write_bytes(path, payload)


class SynopsisStore:
    """Workspace-scoped records plus immutable content-addressed source snapshots."""

    def __init__(self, data_dir: str | Path) -> None:
        self.root = Path(data_dir).expanduser().resolve() / "synopses"
        self.records_root = self.root / "records"
        self.blobs_root = self.root / "blobs" / "sha256"
        self.records_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.blobs_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for path in (self.root, self.records_root, self.blobs_root):
            with suppress(OSError):
                os.chmod(path, 0o700)

    def create(
        self,
        *,
        workspace_scope: str,
        session_id: str,
        source: SourceSnapshot,
        summary: str,
        source_start: int = 0,
        source_end: int | None = None,
        summary_model: str = "",
        expected_source_sha256: str = "",
    ) -> SynopsisRecord:
        scope = _canonical_scope(workspace_scope)
        sid = str(session_id or "")
        if not sid:
            raise SynopsisError("synopsis 属于当前 session；缺少 session id。")
        text = source.text
        if len(text) > MAX_SOURCE_SNAPSHOT_CHARS:
            raise SynopsisError(
                f"source 超过 synopsis snapshot 物理上限 {MAX_SOURCE_SNAPSHOT_CHARS} chars。"
            )
        expected = str(expected_source_sha256 or "").strip().lower()
        if expected and expected != source.source_sha256:
            raise SynopsisError("source SHA 已变化；拒绝把摘要绑定到未确认版本。")
        body = str(summary or "")
        if not body.strip():
            raise SynopsisError("summary 不能为空。")
        if len(body) > MAX_SYNOPSIS_CHARS:
            raise SynopsisError(f"summary 超过物理上限 {MAX_SYNOPSIS_CHARS} chars。")
        start = int(source_start or 0)
        end = len(text) if source_end is None else int(source_end)
        if start < 0 or end < start or end > len(text):
            raise SynopsisError("source_start/source_end 超出 exact source 范围。")
        if end == start:
            raise SynopsisError("summary source range 不能为空。")

        source_blob = text.encode("utf-8")
        blob_path = self._blob_path(source.source_sha256)
        if blob_path.exists():
            try:
                existing = blob_path.read_bytes()
            except OSError as exc:
                raise SynopsisError("synopsis source blob 不可读。") from exc
            if hashlib.sha256(existing).hexdigest() != source.source_sha256:
                raise SynopsisError("synopsis source blob 完整性校验失败。")
        else:
            _atomic_write_bytes(blob_path, source_blob)

        selected = text[start:end]
        synopsis_id = uuid.uuid4().hex
        record = SynopsisRecord(
            version=SYNOPSIS_VERSION,
            synopsis_id=synopsis_id,
            ref=f"{SYNOPSIS_SCHEME}{synopsis_id}",
            workspace_scope=scope,
            session_id=sid,
            # A model-authored summary may contain current-session context beyond the
            # cited source. Never widen it to workspace scope merely because the source
            # itself is workspace-scoped. Cross-session reuse requires a separate,
            # explicit promotion mechanism.
            access_scope="session",
            source_access_scope=source.access_scope,
            source_ref=source.source_ref,
            source_kind=source.source_kind,
            source_sha256=source.source_sha256,
            source_chars=source.source_chars,
            source_complete=source.source_complete,
            source_representation=source.representation,
            origin_sha256=source.origin_sha256,
            source_start=start,
            source_end=end,
            range_sha256=hashlib.sha256(selected.encode("utf-8")).hexdigest(),
            range_chars=len(selected),
            summary=body,
            summary_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            summary_chars=len(body),
            summary_model=str(summary_model or ""),
            created_at=time.time(),
        )
        path = self._record_path(scope, synopsis_id)
        if path.exists():
            raise SynopsisError("synopsis id 冲突，拒绝覆盖。")
        _atomic_write_json(path, asdict(record))
        return record

    def get(
        self, ref: str, *, workspace_scope: str, session_id: str
    ) -> SynopsisRecord | None:
        synopsis_id = _synopsis_id(ref)
        scope = _canonical_scope(workspace_scope)
        path = self._record_path(scope, synopsis_id)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            record = self._from_json(raw)
        except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
            raise SynopsisError("synopsis record 损坏。") from exc
        if record.workspace_scope != scope:
            return None
        if record.session_id != str(session_id or ""):
            return None
        return record

    def read_source(
        self,
        ref: str,
        *,
        workspace_scope: str,
        session_id: str,
        offset: int = 0,
        max_chars: int = MAX_SOURCE_READ_CHARS,
    ) -> dict[str, Any] | None:
        record = self.get(ref, workspace_scope=workspace_scope, session_id=session_id)
        if record is None:
            return None
        text = self._read_blob(record)
        start = max(0, min(int(offset or 0), len(text)))
        width = max(1, min(int(max_chars or MAX_SOURCE_READ_CHARS), MAX_SOURCE_READ_CHARS))
        chunk = text[start : start + width]
        next_offset = start + len(chunk)
        complete = next_offset >= len(text)
        return {
            "synopsis_ref": record.ref,
            "source_ref": record.source_ref,
            "source_sha256": record.source_sha256,
            "source_chars": len(text),
            "source_start": record.source_start,
            "source_end": record.source_end,
            "offset": start,
            "next_offset": None if complete else next_offset,
            "complete": complete,
            "content": chunk,
        }

    def search(
        self,
        *,
        workspace_scope: str,
        session_id: str,
        query: str = "",
        limit: int = 10,
    ) -> list[SynopsisRecord]:
        scope = _canonical_scope(workspace_scope)
        bucket = self.records_root / _workspace_bucket(scope)
        if not bucket.is_dir():
            return []
        q = str(query or "").casefold()
        records: list[SynopsisRecord] = []
        for path in bucket.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                record = self._from_json(raw)
            except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError):
                continue
            if record.workspace_scope != scope:
                continue
            if record.session_id != str(session_id or ""):
                continue
            hay = " ".join(
                (record.ref, record.source_ref, record.source_kind, record.summary)
            ).casefold()
            if q and q not in hay:
                continue
            records.append(record)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records[: max(1, int(limit))]

    def delete_session(self, session_id: str) -> int:
        """Delete all synopsis records owned by one session and GC safe orphan blobs.

        Corrupt remaining records fail closed for blob GC: records already proven to
        belong to the deleted session are removed, but no content-addressed blob is
        deleted unless every remaining record can be enumerated safely.
        """
        sid = str(session_id or "")
        if not sid:
            raise SynopsisError("session_id 不能为空。")
        removed = 0
        for path in self.records_root.glob("*/*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                record = self._from_json(raw)
            except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError):
                continue
            if record.session_id == sid:
                with suppress(FileNotFoundError):
                    path.unlink()
                    removed += 1

        live: set[str] = set()
        gc_safe = True
        for path in self.records_root.glob("*/*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                record = self._from_json(raw)
            except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError):
                gc_safe = False
                break
            live.add(record.source_sha256)
        if gc_safe:
            for blob in self.blobs_root.glob("*/*.txt"):
                if blob.stem not in live:
                    with suppress(FileNotFoundError):
                        blob.unlink()
        return removed

    def _read_blob(self, record: SynopsisRecord) -> str:
        path = self._blob_path(record.source_sha256)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise SynopsisError("synopsis exact source blob 不可读。") from exc
        if hashlib.sha256(data).hexdigest() != record.source_sha256:
            raise SynopsisError("synopsis exact source blob 完整性校验失败。")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SynopsisError("synopsis exact source blob 不是 UTF-8。") from exc
        if len(text) != record.source_chars:
            raise SynopsisError("synopsis exact source 长度校验失败。")
        return text

    def _record_path(self, scope: str, synopsis_id: str) -> Path:
        return self.records_root / _workspace_bucket(scope) / f"{synopsis_id}.json"

    def _blob_path(self, sha256: str) -> Path:
        return self.blobs_root / sha256[:2] / f"{sha256}.txt"

    @staticmethod
    def _from_json(raw: dict[str, Any]) -> SynopsisRecord:
        record = SynopsisRecord(
            version=int(raw["version"]),
            synopsis_id=str(raw["synopsis_id"]),
            ref=str(raw["ref"]),
            workspace_scope=_canonical_scope(str(raw["workspace_scope"])),
            session_id=str(raw.get("session_id") or ""),
            access_scope=str(raw["access_scope"]),  # type: ignore[arg-type]
            source_access_scope=str(raw["source_access_scope"]),  # type: ignore[arg-type]
            source_ref=str(raw["source_ref"]),
            source_kind=str(raw["source_kind"]),
            source_sha256=str(raw["source_sha256"]),
            source_chars=int(raw["source_chars"]),
            source_complete=bool(raw["source_complete"]),
            source_representation=str(raw["source_representation"]),
            origin_sha256=str(raw.get("origin_sha256") or ""),
            source_start=int(raw["source_start"]),
            source_end=int(raw["source_end"]),
            range_sha256=str(raw["range_sha256"]),
            range_chars=int(raw["range_chars"]),
            summary=str(raw["summary"]),
            summary_sha256=str(raw["summary_sha256"]),
            summary_chars=int(raw["summary_chars"]),
            summary_model=str(raw.get("summary_model") or ""),
            created_at=float(raw["created_at"]),
            representation=str(raw.get("representation") or "model_authored_synopsis"),
            task_applicability=str(raw.get("task_applicability") or "not_evaluated"),
        )
        if record.version != SYNOPSIS_VERSION or record.ref != f"{SYNOPSIS_SCHEME}{record.synopsis_id}":
            raise ValueError("invalid synopsis record identity")
        _synopsis_id(record.ref)
        if record.access_scope != "session":
            raise ValueError("synopsis record must remain session-scoped")
        if record.source_access_scope not in {"workspace", "session"}:
            raise ValueError("invalid synopsis source access scope")
        if record.source_chars < 0 or not (0 <= record.source_start < record.source_end <= record.source_chars):
            raise ValueError("invalid synopsis source range")
        if record.range_chars != record.source_end - record.source_start:
            raise ValueError("invalid synopsis range_chars")
        if len(record.source_sha256) != 64 or len(record.range_sha256) != 64 or len(record.summary_sha256) != 64:
            raise ValueError("invalid synopsis hashes")
        if record.summary_chars != len(record.summary):
            raise ValueError("invalid synopsis summary_chars")
        return record


__all__ = [
    "MAX_SOURCE_READ_CHARS",
    "MAX_SOURCE_SNAPSHOT_CHARS",
    "MAX_SYNOPSIS_CHARS",
    "SYNOPSIS_SCHEME",
    "SourceSnapshot",
    "SynopsisError",
    "SynopsisRecord",
    "SynopsisStore",
]
