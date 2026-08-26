"""Evidence Recoverability Contract v1.1 - Phase 1/3 primitives.

This module intentionally does *not* change the current tool/prompt path.  It provides
an offline/shadow-capable immutable BlobStore, owner-scoped EvidenceLedgerStore,
deterministic capture, bounded hydration, and a queryless recent manifest.

Important separations:
- BlobRef: physical immutable bytes identity (content addressed).
- EvidenceRef/EvidenceRecord: logical capture identity + provenance/owner.
- EvidenceState: mutable freshness/availability state.
- Projection is a bounded view over immutable Evidence and never mutates Evidence identity.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

_BLOB_PREFIX = "blob://sha256/"
_EVIDENCE_PREFIX = "evidence://v1/"
_RECORD_DOMAIN = b"erc-v1\x00"


class EvidenceError(RuntimeError):
    """Base error for Evidence Recoverability primitives."""


class EvidenceAuthDeniedError(EvidenceError):
    """The EvidenceRef exists but is not owned by the current scope."""


class EvidenceRefUnknownError(EvidenceError):
    """The EvidenceRef is unknown to the ledger."""


class EvidenceBlobLostError(EvidenceError):
    """The logical record exists but its immutable blob is missing."""


class EvidenceCorruptedError(EvidenceError):
    """The blob bytes no longer match their content-addressed digest."""


class EvidenceLedgerCommitError(EvidenceError):
    """A deterministic EvidenceRef collided with different logical record data."""


class SourceKind(StrEnum):
    FILE = "file"
    COMMAND = "command"
    WEB = "web"
    RUNTIME_SNAPSHOT = "runtime_snapshot"
    CONVERSATION = "conversation"


class SourceVersionPolicy(StrEnum):
    PROBEABLE = "probeable"
    SNAPSHOT_ONLY = "snapshot_only"
    VOLATILE = "volatile"
    VERSIONED = "versioned"


class FreshnessState(StrEnum):
    VERIFIED_CURRENT = "verified_current"
    STALE = "stale"
    UNKNOWN = "unknown"


class AvailabilityState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class RangeType(StrEnum):
    LINE = "line"
    TEXT_CHAR = "text_char"


class EvidenceRepresentation(StrEnum):
    FULL = "full"
    EXCERPT = "excerpt"


@dataclass(frozen=True, slots=True)
class OwnerScope:
    workspace_id: str
    session_id: str

    def __post_init__(self) -> None:
        if not self.workspace_id.strip() or not self.session_id.strip():
            raise ValueError("workspace_id and session_id must be non-empty")

    def to_dict(self) -> dict[str, str]:
        return {"workspace_id": self.workspace_id, "session_id": self.session_id}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> OwnerScope:
        return cls(workspace_id=str(data["workspace_id"]), session_id=str(data["session_id"]))

    @property
    def storage_key(self) -> str:
        raw = f"{self.workspace_id}\x00{self.session_id}".encode()
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class BlobRef:
    ref: str
    sha256: str
    size_bytes: int
    size_chars: int

    def __post_init__(self) -> None:
        expected = f"{_BLOB_PREFIX}{self.sha256}"
        if self.ref != expected or len(self.sha256) != 64:
            raise ValueError("invalid BlobRef")

    def to_dict(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "size_chars": self.size_chars,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> BlobRef:
        return cls(
            ref=str(data["ref"]),
            sha256=str(data["sha256"]),
            size_bytes=_json_int(data["size_bytes"], "size_bytes"),
            size_chars=_json_int(data["size_chars"], "size_chars"),
        )


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    ref: str

    def __post_init__(self) -> None:
        record_id = self.record_id
        if len(record_id) != 64 or any(c not in "0123456789abcdef" for c in record_id):
            raise ValueError("invalid EvidenceRef")

    @property
    def record_id(self) -> str:
        if not self.ref.startswith(_EVIDENCE_PREFIX):
            raise ValueError("invalid EvidenceRef prefix")
        return self.ref.removeprefix(_EVIDENCE_PREFIX)

    def __str__(self) -> str:
        return self.ref


@dataclass(frozen=True, slots=True)
class ProjectionMetadata:
    evidence_ref: EvidenceRef
    representation: EvidenceRepresentation
    projection_complete: bool
    original_chars: int
    visible_chars: int
    temperature: str


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    content: str
    metadata: ProjectionMetadata
    model_capsule: str


@dataclass(frozen=True, slots=True)
class Coverage:
    """Coverage of the *source* represented by this tool observation.

    The Evidence blob is always the complete captured Tool Observation.  Coverage says
    whether that observation covers all or only part of the underlying source.
    """

    unit: str
    start: int
    end_exclusive: int | None
    source_complete: bool

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError("coverage start must be >= 0")
        if self.end_exclusive is not None and self.end_exclusive < self.start:
            raise ValueError("coverage end_exclusive must be >= start")

    def to_dict(self) -> dict[str, object]:
        return {
            "unit": self.unit,
            "start": self.start,
            "end_exclusive": self.end_exclusive,
            "source_complete": self.source_complete,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Coverage:
        end = data.get("end_exclusive")
        return cls(
            unit=str(data["unit"]),
            start=_json_int(data["start"], "start"),
            end_exclusive=None if end is None else _json_int(end, "end_exclusive"),
            source_complete=bool(data["source_complete"]),
        )

    @property
    def label(self) -> str:
        end = "?" if self.end_exclusive is None else str(self.end_exclusive)
        completeness = "source_complete" if self.source_complete else "source_partial"
        return f"{self.unit}:{self.start}-{end}/{completeness}"


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    kind: SourceKind
    locator: str
    version_policy: SourceVersionPolicy
    version_token: str | None = None

    def __post_init__(self) -> None:
        if not self.locator.strip():
            raise ValueError("source locator must be non-empty")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "locator": self.locator,
            "version_policy": self.version_policy.value,
            "version_token": self.version_token,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SourceIdentity:
        token = data.get("version_token")
        return cls(
            kind=SourceKind(str(data["kind"])),
            locator=str(data["locator"]),
            version_policy=SourceVersionPolicy(str(data["version_policy"])),
            version_token=None if token is None else str(token),
        )

    @property
    def safe_locator(self) -> str:
        if self.kind is SourceKind.FILE:
            return self.locator
        if self.kind is SourceKind.COMMAND:
            digest = hashlib.sha256(self.locator.encode()).hexdigest()[:12]
            return f"command#{digest}"
        if self.kind is SourceKind.WEB:
            parts = urlsplit(self.locator)
            return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        return self.locator


@dataclass(frozen=True, slots=True)
class Provenance:
    producer: str
    authority: str = ""
    scope: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"producer": self.producer, "authority": self.authority, "scope": self.scope}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Provenance:
        return cls(
            producer=str(data.get("producer", "")),
            authority=str(data.get("authority", "")),
            scope=str(data.get("scope", "")),
        )


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_ref: EvidenceRef
    owner: OwnerScope
    blob_ref: BlobRef
    stable_capture_id: str
    acquired_at: str
    tool_name: str
    tool_call_id: str | None
    source: SourceIdentity
    coverage: Coverage
    provenance: Provenance

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_ref": self.evidence_ref.ref,
            "owner": self.owner.to_dict(),
            "blob_ref": self.blob_ref.to_dict(),
            "stable_capture_id": self.stable_capture_id,
            "acquired_at": self.acquired_at,
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "source": self.source.to_dict(),
            "coverage": self.coverage.to_dict(),
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> EvidenceRecord:
        tool_call_id = data.get("tool_call_id")
        return cls(
            evidence_ref=EvidenceRef(str(data["evidence_ref"])),
            owner=OwnerScope.from_dict(_as_dict(data["owner"])),
            blob_ref=BlobRef.from_dict(_as_dict(data["blob_ref"])),
            stable_capture_id=str(data["stable_capture_id"]),
            acquired_at=str(data["acquired_at"]),
            tool_name=str(data["tool_name"]),
            tool_call_id=None if tool_call_id is None else str(tool_call_id),
            source=SourceIdentity.from_dict(_as_dict(data["source"])),
            coverage=Coverage.from_dict(_as_dict(data["coverage"])),
            provenance=Provenance.from_dict(_as_dict(data["provenance"])),
        )


@dataclass(frozen=True, slots=True)
class EvidenceState:
    evidence_ref: EvidenceRef
    freshness: FreshnessState
    availability: AvailabilityState
    updated_at: str
    semantic_links: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "evidence_ref": self.evidence_ref.ref,
            "freshness": self.freshness.value,
            "availability": self.availability.value,
            "updated_at": self.updated_at,
            "semantic_links": list(self.semantic_links),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> EvidenceState:
        links_raw = data.get("semantic_links", [])
        links = links_raw if isinstance(links_raw, list) else []
        return cls(
            evidence_ref=EvidenceRef(str(data["evidence_ref"])),
            freshness=FreshnessState(str(data["freshness"])),
            availability=AvailabilityState(str(data["availability"])),
            updated_at=str(data["updated_at"]),
            semantic_links=tuple(str(v) for v in links if isinstance(v, str)),
        )

    def with_freshness(self, freshness: FreshnessState, *, updated_at: str) -> EvidenceState:
        return replace(self, freshness=freshness, updated_at=updated_at)


@dataclass(frozen=True, slots=True)
class CaptureRequest:
    owner: OwnerScope
    stable_capture_id: str
    raw_observation: str
    acquired_at: datetime
    tool_name: str
    tool_call_id: str | None
    source: SourceIdentity
    coverage: Coverage
    provenance: Provenance


@dataclass(frozen=True, slots=True)
class CaptureResult:
    evidence_ref: EvidenceRef
    blob_ref: BlobRef
    original_chars: int


@dataclass(frozen=True, slots=True)
class HydrationResult:
    evidence_ref: EvidenceRef
    content: str
    range_type: RangeType
    start: int
    count: int
    next_start: int | None
    blob_sha256: str
    range_sha256: str
    freshness: FreshnessState


@dataclass(frozen=True, slots=True)
class SearchHit:
    evidence_ref: EvidenceRef
    snippet: str
    snippet_start_char: int
    source_label: str
    acquired_at: str
    freshness: FreshnessState
    tool_name: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    hits: tuple[SearchHit, ...]
    total_hits: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RecoveryManifestEntry:
    evidence_ref: EvidenceRef
    stable_capture_id: str
    source_label: str
    coverage_label: str
    acquired_at: str
    freshness: FreshnessState
    availability: AvailabilityState


@dataclass(frozen=True, slots=True)
class RecoveryManifest:
    entries: tuple[RecoveryManifestEntry, ...]
    ledger_version: str
    truncated: bool


class BlobStore:
    """Immutable UTF-8 blob storage keyed by SHA-256 of exact observation bytes."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def put_text(self, content: str) -> BlobRef:
        data = content.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        ref = BlobRef(
            ref=f"{_BLOB_PREFIX}{digest}",
            sha256=digest,
            size_bytes=len(data),
            size_chars=len(content),
        )
        path = self._path(ref)
        with self._lock, _file_lock(self.root / ".blob.lock"):
            if path.exists():
                existing = path.read_bytes()
                if hashlib.sha256(existing).hexdigest() != digest:
                    raise EvidenceCorruptedError(f"existing blob digest mismatch: {ref.ref}")
                return ref
            _atomic_write_bytes(path, data)
        return ref

    def read_text(self, ref: BlobRef) -> str:
        path = self._path(ref)
        if not path.exists():
            raise EvidenceBlobLostError(ref.ref)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != ref.sha256:
            raise EvidenceCorruptedError(ref.ref)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EvidenceCorruptedError(f"blob is not valid UTF-8: {ref.ref}") from exc

    def read_text_chars(self, ref: BlobRef, *, start: int, limit: int) -> str:
        _validate_range(start, limit)
        return self.read_text(ref)[start : start + limit]

    def read_lines(self, ref: BlobRef, *, start_line: int, limit: int) -> str:
        _validate_range(start_line, limit)
        lines = self.read_text(ref).splitlines(keepends=True)
        return "".join(lines[start_line : start_line + limit])

    def verify(self, ref: BlobRef) -> bool:
        try:
            self.read_text(ref)
        except (EvidenceBlobLostError, EvidenceCorruptedError):
            return False
        return True

    def delete(self, ref: BlobRef) -> bool:
        """Physical delete primitive. Caller must prove the blob is unreferenced."""
        path = self._path(ref)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def _path(self, ref: BlobRef) -> Path:
        return self.root / "sha256" / ref.sha256[:2] / f"{ref.sha256}.blob"


class EvidenceLedgerStore:
    """Durable logical Evidence records isolated by workspace/session owner."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def append_record(self, record: EvidenceRecord, state: EvidenceState) -> None:
        if record.evidence_ref != state.evidence_ref:
            raise ValueError("record/state EvidenceRef mismatch")
        expected = make_evidence_ref(record.owner, record.stable_capture_id, record.blob_ref)
        if expected != record.evidence_ref:
            raise EvidenceLedgerCommitError("EvidenceRef does not match deterministic record identity")

        record_path = self._record_path(record.owner, record.evidence_ref)
        state_path = self._state_path(record.owner, record.evidence_ref)
        index_path = self._ref_index_path(record.evidence_ref)
        owner_meta = self._owner_dir(record.owner) / "owner.json"

        with self._lock, _file_lock(self.root / ".ledger.lock"):
            _ensure_same_or_write(owner_meta, record.owner.to_dict())
            if record_path.exists():
                existing = EvidenceRecord.from_dict(_read_json(record_path))
                if existing != record:
                    raise EvidenceLedgerCommitError(
                        f"deterministic EvidenceRef collision: {record.evidence_ref.ref}"
                    )
            else:
                _atomic_write_json(record_path, record.to_dict())

            # A replay must never reset a state that later became STALE/UNAVAILABLE.
            if not state_path.exists():
                _atomic_write_json(state_path, state.to_dict())

            index_data = {"owner_key": record.owner.storage_key}
            _ensure_same_or_write(index_path, index_data)

    def get_record(self, owner: OwnerScope, ref: EvidenceRef) -> EvidenceRecord | None:
        path = self._record_path(owner, ref)
        if not path.exists():
            return None
        record = EvidenceRecord.from_dict(_read_json(path))
        if record.owner != owner:
            return None
        return record

    def get_state(self, owner: OwnerScope, ref: EvidenceRef) -> EvidenceState | None:
        if self.get_record(owner, ref) is None:
            return None
        path = self._state_path(owner, ref)
        if not path.exists():
            return None
        return EvidenceState.from_dict(_read_json(path))

    def require_authorized(self, owner: OwnerScope, ref: EvidenceRef) -> EvidenceRecord:
        record = self.get_record(owner, ref)
        if record is not None:
            return record
        index = self._ref_index_path(ref)
        if index.exists():
            data = _read_json(index)
            if str(data.get("owner_key", "")) != owner.storage_key:
                raise EvidenceAuthDeniedError(ref.ref)
        raise EvidenceRefUnknownError(ref.ref)

    def update_state(self, owner: OwnerScope, state: EvidenceState) -> None:
        self.require_authorized(owner, state.evidence_ref)
        path = self._state_path(owner, state.evidence_ref)
        with self._lock, _file_lock(self.root / ".ledger.lock"):
            _atomic_write_json(path, state.to_dict())

    def list_recent(self, owner: OwnerScope, *, limit: int) -> list[EvidenceRecord]:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        record_dir = self._owner_dir(owner) / "records"
        if not record_dir.exists() or limit == 0:
            return []
        records: list[EvidenceRecord] = []
        for path in record_dir.glob("*.json"):
            try:
                record = EvidenceRecord.from_dict(_read_json(path))
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            if record.owner == owner:
                records.append(record)
        records.sort(key=lambda item: (item.acquired_at, item.evidence_ref.ref), reverse=True)
        return records[:limit]

    def count(self, owner: OwnerScope) -> int:
        record_dir = self._owner_dir(owner) / "records"
        if not record_dir.exists():
            return 0
        return sum(1 for _ in record_dir.glob("*.json"))

    def find_by_source(self, owner: OwnerScope, locator: str) -> list[EvidenceRecord]:
        return [r for r in self.list_recent(owner, limit=max(1, self.count(owner))) if r.source.locator == locator]

    def find_by_tool_call_id(self, owner: OwnerScope, tool_call_id: str) -> list[EvidenceRecord]:
        if not tool_call_id:
            return []
        return [
            r
            for r in self.list_recent(owner, limit=max(1, self.count(owner)))
            if r.tool_call_id == tool_call_id
        ]

    def owners_for_session(self, session_id: str) -> list[OwnerScope]:
        if not session_id:
            return []
        owners_root = self.root / "owners"
        if not owners_root.exists():
            return []
        owners: list[OwnerScope] = []
        for path in owners_root.glob("*/owner.json"):
            try:
                owner = OwnerScope.from_dict(_read_json(path))
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            if owner.session_id == session_id:
                owners.append(owner)
        owners.sort(key=lambda item: (item.workspace_id, item.session_id))
        return owners

    def ledger_version(self, owner: OwnerScope) -> str:
        rows: list[dict[str, object]] = []
        for record in self.list_recent(owner, limit=max(1, self.count(owner))):
            state = self.get_state(owner, record.evidence_ref)
            rows.append(
                {
                    "ref": record.evidence_ref.ref,
                    "state": None if state is None else state.to_dict(),
                }
            )
        raw = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()

    def blob_refcount(self, ref: BlobRef) -> int:
        count = 0
        owners = self.root / "owners"
        if not owners.exists():
            return 0
        for path in owners.glob("*/records/*.json"):
            try:
                record = EvidenceRecord.from_dict(_read_json(path))
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            if record.blob_ref.ref == ref.ref:
                count += 1
        return count

    def remove_owner(self, owner: OwnerScope) -> list[BlobRef]:
        owner_dir = self._owner_dir(owner)
        records = self.list_recent(owner, limit=max(1, self.count(owner)))
        with self._lock, _file_lock(self.root / ".ledger.lock"):
            for record in records:
                with suppress(FileNotFoundError):
                    self._ref_index_path(record.evidence_ref).unlink()
            if owner_dir.exists():
                shutil.rmtree(owner_dir)
        return [record.blob_ref for record in records]

    def _owner_dir(self, owner: OwnerScope) -> Path:
        return self.root / "owners" / owner.storage_key

    def _record_path(self, owner: OwnerScope, ref: EvidenceRef) -> Path:
        return self._owner_dir(owner) / "records" / f"{ref.record_id}.json"

    def _state_path(self, owner: OwnerScope, ref: EvidenceRef) -> Path:
        return self._owner_dir(owner) / "states" / f"{ref.record_id}.json"

    def _ref_index_path(self, ref: EvidenceRef) -> Path:
        return self.root / "ref_index" / ref.record_id[:2] / f"{ref.record_id}.json"


class EvidenceCapture:
    """Shadow-capable capture service. It never executes or re-executes a source action."""

    def __init__(self, blobs: BlobStore, ledger: EvidenceLedgerStore) -> None:
        self.blobs = blobs
        self.ledger = ledger

    def capture(self, request: CaptureRequest) -> CaptureResult:
        # Capture and physical blob GC serialize on the same durable lock.  This closes
        # the race where GC observes refcount=0, another process commits a new record to
        # the same content-addressed blob, and GC then unlinks bytes still referenced.
        with _file_lock(self.ledger.root / ".gc.lock"):
            blob_ref = self.blobs.put_text(request.raw_observation)
            evidence_ref = make_evidence_ref(request.owner, request.stable_capture_id, blob_ref)

            # Replay semantics: the logical capture event is identified by owner + stable_capture_id
            # + immutable blob.  Rebuilding a provider projection later must not manufacture a new
            # acquired_at for the same event.  Preserve the first committed record/state exactly.
            existing = self.ledger.get_record(request.owner, evidence_ref)
            if existing is not None:
                if not _capture_request_matches_record(request, blob_ref, existing):
                    raise EvidenceLedgerCommitError(
                        f"stable capture replay metadata conflict: {evidence_ref.ref}"
                    )
                return CaptureResult(
                    evidence_ref=existing.evidence_ref,
                    blob_ref=existing.blob_ref,
                    original_chars=existing.blob_ref.size_chars,
                )

            acquired_at = _iso(request.acquired_at)
            record = EvidenceRecord(
                evidence_ref=evidence_ref,
                owner=request.owner,
                blob_ref=blob_ref,
                stable_capture_id=request.stable_capture_id,
                acquired_at=acquired_at,
                tool_name=request.tool_name,
                tool_call_id=request.tool_call_id,
                source=request.source,
                coverage=request.coverage,
                provenance=request.provenance,
            )
            initial_freshness = (
                FreshnessState.VERIFIED_CURRENT
                if request.source.version_policy is SourceVersionPolicy.PROBEABLE
                and request.source.version_token is not None
                else FreshnessState.UNKNOWN
            )
            state = EvidenceState(
                evidence_ref=evidence_ref,
                freshness=initial_freshness,
                availability=AvailabilityState.AVAILABLE,
                updated_at=acquired_at,
            )
            self.ledger.append_record(record, state)
            return CaptureResult(
                evidence_ref=evidence_ref,
                blob_ref=blob_ref,
                original_chars=len(request.raw_observation),
            )


class EvidenceHydration:
    """Owner-aware, bounded exact hydration from already captured observations."""

    def __init__(self, blobs: BlobStore, ledger: EvidenceLedgerStore, *, max_limit: int = 4000) -> None:
        if max_limit <= 0:
            raise ValueError("max_limit must be > 0")
        self.blobs = blobs
        self.ledger = ledger
        self.max_limit = max_limit

    def read(
        self,
        *,
        owner: OwnerScope,
        evidence_ref: EvidenceRef,
        range_type: RangeType,
        start: int = 0,
        limit: int = 200,
    ) -> HydrationResult:
        if not isinstance(evidence_ref, EvidenceRef):
            raise TypeError("model-facing hydration requires EvidenceRef, not BlobRef/hash")
        _validate_range(start, limit)
        if limit > self.max_limit:
            raise ValueError(f"limit exceeds maximum {self.max_limit}")

        record = self.ledger.require_authorized(owner, evidence_ref)
        text = self.blobs.read_text(record.blob_ref)
        if range_type is RangeType.TEXT_CHAR:
            content = text[start : start + limit]
            count = len(content)
            next_start = start + count if start + count < len(text) else None
        elif range_type is RangeType.LINE:
            lines = text.splitlines(keepends=True)
            selected = lines[start : start + limit]
            content = "".join(selected)
            count = len(selected)
            next_start = start + count if start + count < len(lines) else None
        else:
            raise ValueError(f"unsupported range_type: {range_type}")

        state = self.ledger.get_state(owner, evidence_ref)
        freshness = FreshnessState.UNKNOWN if state is None else state.freshness
        return HydrationResult(
            evidence_ref=evidence_ref,
            content=content,
            range_type=range_type,
            start=start,
            count=count,
            next_start=next_start,
            blob_sha256=record.blob_ref.sha256,
            range_sha256=hashlib.sha256(content.encode()).hexdigest(),
            freshness=freshness,
        )


class EvidenceFreshness:
    """Refresh source freshness without re-executing the original source action.

    File evidence is probeable by the captured stat token.  Command/web evidence remains
    snapshot/volatile and therefore UNKNOWN.  Runtime evidence is UNKNOWN until a producer
    supplies an external version resolver; ERC never invents currentness.
    """

    def __init__(self, ledger: EvidenceLedgerStore) -> None:
        self.ledger = ledger

    def refresh(self, *, owner: OwnerScope, evidence_ref: EvidenceRef) -> EvidenceState:
        record = self.ledger.require_authorized(owner, evidence_ref)
        state = self.ledger.get_state(owner, evidence_ref)
        now = datetime.now(UTC).isoformat()
        current = state or EvidenceState(
            evidence_ref=evidence_ref,
            freshness=FreshnessState.UNKNOWN,
            availability=AvailabilityState.UNKNOWN,
            updated_at=now,
        )

        freshness = self._probe(owner, record)
        availability = (
            AvailabilityState.AVAILABLE
            if current.availability is not AvailabilityState.UNAVAILABLE
            else current.availability
        )
        if freshness is current.freshness and availability is current.availability:
            return current
        updated = replace(
            current,
            freshness=freshness,
            availability=availability,
            updated_at=now,
        )
        self.ledger.update_state(owner, updated)
        return updated

    @staticmethod
    def _probe(owner: OwnerScope, record: EvidenceRecord) -> FreshnessState:
        source = record.source
        if source.kind is not SourceKind.FILE or source.version_policy is not SourceVersionPolicy.PROBEABLE:
            return FreshnessState.UNKNOWN
        token = source.version_token
        if not token or not token.startswith("stat:"):
            return FreshnessState.UNKNOWN
        parts = token.split(":")
        if len(parts) != 3:
            return FreshnessState.UNKNOWN
        try:
            expected_mtime = int(parts[1])
            expected_size = int(parts[2])
        except ValueError:
            return FreshnessState.UNKNOWN

        path = Path(source.locator).expanduser()
        if not path.is_absolute():
            path = Path(owner.workspace_id) / path
        try:
            stat = path.stat()
        except OSError:
            return FreshnessState.STALE
        if (stat.st_mtime_ns, stat.st_size) == (expected_mtime, expected_size):
            return FreshnessState.VERIFIED_CURRENT
        return FreshnessState.STALE


class EvidenceSearch:
    """Owner-scoped deterministic lexical discovery over exact Evidence blobs.

    Query grammar is deliberately small and inspectable:
    - whitespace tokens are ANDed;
    - explicit ``OR`` separates alternative AND groups;
    - shell-style quoted text is one phrase token.
    """

    def __init__(
        self,
        blobs: BlobStore,
        ledger: EvidenceLedgerStore,
        *,
        snippet_chars: int = 500,
    ) -> None:
        if snippet_chars < 80:
            raise ValueError("snippet_chars must be >= 80")
        self.blobs = blobs
        self.ledger = ledger
        self.snippet_chars = snippet_chars

    def search(
        self,
        *,
        owner: OwnerScope,
        query: str,
        limit: int = 10,
        tool_name: str | None = None,
    ) -> SearchResult:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        groups = _parse_evidence_query(query)
        count = self.ledger.count(owner)
        records = self.ledger.list_recent(owner, limit=max(1, count))
        hits: list[SearchHit] = []
        total_hits = 0
        for record in records:
            if tool_name and record.tool_name != tool_name:
                continue
            try:
                text = self.blobs.read_text(record.blob_ref)
            except (EvidenceBlobLostError, EvidenceCorruptedError):
                continue
            matched_terms = _matching_query_terms(text, groups)
            if matched_terms is None:
                continue
            total_hits += 1
            if len(hits) >= limit:
                continue
            state = self.ledger.get_state(owner, record.evidence_ref)
            freshness = FreshnessState.UNKNOWN if state is None else state.freshness
            snippet, start = _match_centered_snippet(
                text,
                matched_terms,
                max_chars=self.snippet_chars,
            )
            hits.append(
                SearchHit(
                    evidence_ref=record.evidence_ref,
                    snippet=snippet,
                    snippet_start_char=start,
                    source_label=f"{record.tool_name}:{record.source.safe_locator}",
                    acquired_at=record.acquired_at,
                    freshness=freshness,
                    tool_name=record.tool_name,
                )
            )
        return SearchResult(hits=tuple(hits), total_hits=total_hits)


class ProjectionEngine:
    """Deterministic bounded projection over an already-captured observation.

    Temperature expresses decision relevance, not representation size.  In particular, a
    large HOT observation remains eligible for an excerpt; the durable EvidenceRef is the
    recovery path for omitted bytes.
    """

    _MARKER = "\n…[evidence excerpt; exact omitted content via read_evidence]…\n"

    def project(
        self,
        content: str,
        *,
        evidence_ref: EvidenceRef,
        source_label: str,
        coverage_label: str,
        budget_chars: int,
        temperature: str = "hot",
    ) -> ProjectionResult:
        if budget_chars < 128:
            raise ValueError("projection budget_chars must be >= 128")
        original_chars = len(content)
        if original_chars <= budget_chars:
            projected = content
            representation = EvidenceRepresentation.FULL
            complete = True
        else:
            available = max(2, budget_chars - len(self._MARKER))
            head_chars = max(1, int(available * 0.6))
            tail_chars = max(1, available - head_chars)
            projected = content[:head_chars] + self._MARKER + content[-tail_chars:]
            if len(projected) > budget_chars:
                projected = projected[:budget_chars]
            representation = EvidenceRepresentation.EXCERPT
            complete = False

        capsule = self.render_capsule(
            evidence_ref=evidence_ref,
            source_label=source_label,
            coverage_label=coverage_label,
            representation=representation,
            projection_complete=complete,
        )
        return ProjectionResult(
            content=projected,
            metadata=ProjectionMetadata(
                evidence_ref=evidence_ref,
                representation=representation,
                projection_complete=complete,
                original_chars=original_chars,
                visible_chars=len(projected),
                temperature=temperature,
            ),
            model_capsule=capsule,
        )

    @staticmethod
    def render_capsule(
        *,
        evidence_ref: EvidenceRef,
        source_label: str,
        coverage_label: str,
        representation: EvidenceRepresentation,
        projection_complete: bool,
    ) -> str:
        def _one_line(value: str, limit: int) -> str:
            return " ".join(value.replace("[", "(").replace("]", ")").split())[:limit]

        source = _one_line(source_label, 180)
        coverage = _one_line(coverage_label, 120)
        complete = "true" if projection_complete else "false"
        return (
            "[evidence]\n"
            f"ref={evidence_ref.ref}\n"
            f"source={source}\n"
            f"coverage={coverage}\n"
            f"projection={representation.value}\n"
            f"complete={complete}\n"
            "recover=read_evidence\n"
            "[/evidence]"
        )


class ManifestProjector:
    """Build a bounded queryless RECENT manifest from durable ledger state."""

    def __init__(self, ledger: EvidenceLedgerStore) -> None:
        self.ledger = ledger

    def build_recent(self, *, owner: OwnerScope, limit: int) -> RecoveryManifest:
        if limit <= 0:
            raise ValueError("manifest limit must be > 0")
        count = self.ledger.count(owner)
        all_records = self.ledger.list_recent(owner, limit=max(1, count))
        primary = [r for r in all_records if r.source.kind is not SourceKind.CONVERSATION]
        conversation = [r for r in all_records if r.source.kind is SourceKind.CONVERSATION]
        records = (primary + conversation)[:limit]
        entries: list[RecoveryManifestEntry] = []
        for record in records:
            state = self.ledger.get_state(owner, record.evidence_ref)
            freshness = FreshnessState.UNKNOWN if state is None else state.freshness
            availability = AvailabilityState.UNKNOWN if state is None else state.availability
            entries.append(
                RecoveryManifestEntry(
                    evidence_ref=record.evidence_ref,
                    stable_capture_id=record.stable_capture_id,
                    source_label=f"{record.tool_name}:{record.source.safe_locator}",
                    coverage_label=record.coverage.label,
                    acquired_at=record.acquired_at,
                    freshness=freshness,
                    availability=availability,
                )
            )
        return RecoveryManifest(
            entries=tuple(entries),
            ledger_version=self.ledger.ledger_version(owner),
            truncated=self.ledger.count(owner) > len(entries),
        )


def render_recovery_manifest(manifest: RecoveryManifest) -> str:
    """Render a bounded provider-neutral recovery index as a tail user-context frame."""
    if not manifest.entries:
        return ""
    lines = [
        "[上下文注入·Evidence Recovery Manifest·非新指令]",
        f"ledger_version={manifest.ledger_version[:16]} entries={len(manifest.entries)} "
        f"truncated={'true' if manifest.truncated else 'false'}",
        "用途=恢复此前已获取/已压缩证据；优先 list_evidence/search_evidence 定位，read_evidence 精确分页取回；不要仅因上下文不可见而重跑原 source。",
    ]
    for entry in manifest.entries:
        currentness = (
            "current"
            if entry.freshness is FreshnessState.VERIFIED_CURRENT
            else "historical_only"
            if entry.freshness is FreshnessState.STALE
            else "unverified"
        )
        lines.append(
            f"- ref={entry.evidence_ref.ref} source={entry.source_label} "
            f"coverage={entry.coverage_label} freshness={entry.freshness.value} "
            f"currentness={currentness}"
        )
    lines.append("[/Evidence Recovery Manifest]")
    return "\n".join(lines)


def make_capture_request(
    *,
    owner: OwnerScope,
    stable_capture_id: str,
    raw_observation: str,
    acquired_at: datetime,
    tool_name: str,
    tool_call_id: str | None,
    source: SourceIdentity,
    coverage: Coverage,
    provenance: Provenance,
) -> CaptureRequest:
    if not stable_capture_id.strip():
        raise ValueError("stable_capture_id must be non-empty")
    if not tool_name.strip():
        raise ValueError("tool_name must be non-empty")
    if acquired_at.tzinfo is None:
        raise ValueError("acquired_at must be timezone-aware")
    return CaptureRequest(
        owner=owner,
        stable_capture_id=stable_capture_id,
        raw_observation=raw_observation,
        acquired_at=acquired_at,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        source=source,
        coverage=coverage,
        provenance=provenance,
    )


def make_evidence_ref(owner: OwnerScope, stable_capture_id: str, blob_ref: BlobRef) -> EvidenceRef:
    if not stable_capture_id.strip():
        raise ValueError("stable_capture_id must be non-empty")
    h = hashlib.sha256()
    h.update(_RECORD_DOMAIN)
    for value in (owner.workspace_id, owner.session_id, stable_capture_id, blob_ref.sha256):
        encoded = value.encode("utf-8")
        h.update(len(encoded).to_bytes(8, "big"))
        h.update(encoded)
    return EvidenceRef(f"{_EVIDENCE_PREFIX}{h.hexdigest()}")


def _iso(value: datetime) -> str:
    return value.isoformat()


def _validate_range(start: int, limit: int) -> None:
    if start < 0:
        raise ValueError("start must be >= 0")
    if limit <= 0:
        raise ValueError("limit must be > 0")


def _capture_request_matches_record(
    request: CaptureRequest, blob_ref: BlobRef, record: EvidenceRecord
) -> bool:
    """Compare immutable capture semantics while intentionally ignoring replay clock time."""
    return (
        record.owner == request.owner
        and record.blob_ref == blob_ref
        and record.stable_capture_id == request.stable_capture_id
        and record.tool_name == request.tool_name
        and record.tool_call_id == request.tool_call_id
        and record.source == request.source
        and record.coverage == request.coverage
        and record.provenance == request.provenance
    )


def _parse_evidence_query(query: str) -> tuple[tuple[str, ...], ...]:
    query = query.strip()
    if not query:
        raise ValueError("query must be non-empty")
    try:
        tokens = shlex.split(query)
    except ValueError as exc:
        raise ValueError(f"invalid quoted query: {exc}") from exc
    if not tokens:
        raise ValueError("query must be non-empty")
    groups: list[list[str]] = [[]]
    for token in tokens:
        if token.upper() == "OR":
            if not groups[-1]:
                raise ValueError("OR requires terms on both sides")
            groups.append([])
            continue
        groups[-1].append(token.casefold())
    if not groups[-1]:
        raise ValueError("OR requires terms on both sides")
    return tuple(tuple(group) for group in groups)


def _matching_query_terms(
    text: str, groups: tuple[tuple[str, ...], ...]
) -> tuple[str, ...] | None:
    folded = text.casefold()
    for group in groups:
        if all(term in folded for term in group):
            return group
    return None


def _match_centered_snippet(
    text: str, terms: tuple[str, ...], *, max_chars: int
) -> tuple[str, int]:
    folded = text.casefold()
    positions: list[tuple[int, str]] = []
    for term in terms:
        pos = folded.find(term)
        if pos >= 0:
            positions.append((pos, term))
    if not positions:
        return text[:max_chars], 0
    positions.sort()
    first = positions[0][0]
    last_end = max(pos + len(term) for pos, term in positions)
    if last_end - first <= max_chars - 20:
        slack = max_chars - (last_end - first)
        start = max(0, first - slack // 2)
        end = min(len(text), start + max_chars)
        start = max(0, end - max_chars)
        return text[start:end], start

    # Widely separated AND terms: deterministic per-match fragments ensure every required
    # term is visible instead of returning a misleading head-only preview.
    separator = " … "
    per_term = max(24, (max_chars - len(separator) * (len(positions) - 1)) // len(positions))
    fragments: list[str] = []
    for pos, term in positions:
        left = max(0, pos - max(8, (per_term - len(term)) // 2))
        fragments.append(text[left : left + per_term])
    snippet = separator.join(fragments)[:max_chars]
    return snippet, first


def _json_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{field} must be an integer")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an integer") from exc


def _as_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return {str(k): v for k, v in value.items()}


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return _as_dict(value)


def _ensure_same_or_write(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists():
        if _read_json(path) != dict(payload):
            raise EvidenceLedgerCommitError(f"immutable index mismatch: {path}")
        return
    _atomic_write_json(path, payload)


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    data = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    _atomic_write_bytes(path, data)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.{uuid4().hex}.tmp"
    )
    try:
        with tmp.open("xb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        with suppress(FileNotFoundError):
            tmp.unlink()


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass  # best-effort directory fsync; blob file itself is already durable
    finally:
        os.close(fd)


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+")
    try:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass  # non-POSIX fallback: in-process RLock still serializes this store instance
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass  # unlock is best-effort during teardown/non-POSIX fallback
        fh.close()
