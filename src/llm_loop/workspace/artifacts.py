"""Workspace-scoped immutable artifact identities.

Artifacts are mechanical snapshots of exact bytes produced by an execution-owned
workspace mutation.  The model sees only an opaque ``artifact://v1/<id>`` ref plus
workspace-relative path/hash/size facts.  Host paths, task relevance and completion
judgements are deliberately outside this store.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

ARTIFACT_SCHEME = "artifact://v1/"
_ARTIFACT_ID_LEN = 32
_METADATA_VERSION = 1


class ArtifactError(ValueError):
    """An artifact reference cannot be resolved without guessing."""


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    artifact_id: str
    ref: str
    workspace_scope: str
    relative_path: str
    size_bytes: int
    sha256: str
    created_at: float
    owner_session_id: str
    execution_id: str
    tool_call_id: str
    tool_name: str
    effect_kind: str

    def public_facts(self) -> dict[str, object]:
        """Provider-safe identity facts; absolute host paths never leave the store."""
        return {
            "artifact_ref": self.ref,
            "path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "created_at": self.created_at,
            "artifact_identity": "immutable_snapshot",
            "task_applicability": "not_evaluated",
        }


@dataclass(frozen=True, slots=True)
class ArtifactResolution:
    record: ArtifactRecord
    workspace_path_state: str
    current_sha256: str | None = None
    current_size_bytes: int | None = None
    read_error_type: str | None = None

    def public_facts(self) -> dict[str, object]:
        facts = self.record.public_facts()
        facts["workspace_path_state"] = self.workspace_path_state
        if self.current_sha256 is not None:
            facts["workspace_path_sha256"] = self.current_sha256
        if self.current_size_bytes is not None:
            facts["workspace_path_size_bytes"] = self.current_size_bytes
        if self.read_error_type is not None:
            facts["workspace_path_read_error_type"] = self.read_error_type
        return facts


def _canonical_workspace_scope(root: str | Path | None) -> str:
    """Canonical mechanical workspace owner identity."""
    raw = Path(root).expanduser() if root else Path.cwd()
    return str(raw.resolve())


def workspace_scope(root: str | Path | None) -> str:
    return _canonical_workspace_scope(root)


def _workspace_bucket(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:32]


def _artifact_id(ref: str) -> str:
    if not isinstance(ref, str) or not ref.startswith(ARTIFACT_SCHEME):
        raise ArtifactError("artifact 引用格式无效。")
    artifact_id = ref[len(ARTIFACT_SCHEME) :]
    if len(artifact_id) != _ARTIFACT_ID_LEN:
        raise ArtifactError("artifact 引用格式无效。")
    try:
        int(artifact_id, 16)
    except ValueError as exc:
        raise ArtifactError("artifact 引用格式无效。") from exc
    return artifact_id


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_bytes(data)
        with suppress(OSError):
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        with suppress(OSError):
            os.chmod(path, 0o600)
    finally:
        with suppress(OSError):
            tmp.unlink(missing_ok=True)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    _atomic_write_bytes(path, text)


def _safe_relative_path(value: str) -> PurePosixPath:
    raw = str(value or "").replace("\\", "/")
    rel = PurePosixPath(raw)
    if not raw or rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise ArtifactError("artifact 持久化路径字段无效。")
    return rel


class WorkspaceArtifactStore:
    """Durable workspace ownership + immutable content-addressed artifact bytes."""

    def __init__(self, data_dir: str | Path) -> None:
        self.root = Path(data_dir).expanduser().resolve() / "artifacts"
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
        canonical_path: str,
        data: bytes,
        owner_session_id: str,
        execution_id: str,
        tool_call_id: str,
        tool_name: str,
        effect_kind: str,
    ) -> ArtifactRecord:
        scope = _canonical_workspace_scope(workspace_scope)
        workspace = Path(scope)
        target = Path(canonical_path).expanduser().resolve()
        try:
            rel = target.relative_to(workspace)
        except ValueError as exc:
            raise ArtifactError("artifact 目标路径越出当前工作区。") from exc
        relative_path = _safe_relative_path(rel.as_posix()).as_posix()
        payload = bytes(data)
        digest = hashlib.sha256(payload).hexdigest()
        blob_path = self._blob_path(digest)
        if blob_path.exists():
            try:
                existing = blob_path.read_bytes()
            except OSError as exc:
                raise ArtifactError("artifact blob 不可读。") from exc
            if len(existing) != len(payload) or hashlib.sha256(existing).hexdigest() != digest:
                raise ArtifactError("artifact blob 完整性校验失败。")
        else:
            _atomic_write_bytes(blob_path, payload)

        artifact_id = uuid.uuid4().hex
        ref = f"{ARTIFACT_SCHEME}{artifact_id}"
        record = ArtifactRecord(
            artifact_id=artifact_id,
            ref=ref,
            workspace_scope=scope,
            relative_path=relative_path,
            size_bytes=len(payload),
            sha256=digest,
            created_at=time.time(),
            owner_session_id=str(owner_session_id or ""),
            execution_id=str(execution_id or ""),
            tool_call_id=str(tool_call_id or ""),
            tool_name=str(tool_name or ""),
            effect_kind=str(effect_kind or ""),
        )
        record_path = self._record_path(scope, artifact_id)
        if record_path.exists():
            raise ArtifactError("artifact id 冲突，拒绝覆盖既有记录。")
        record_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            os.chmod(record_path.parent, 0o700)
        _atomic_write_json(record_path, self._to_json(record))
        return record

    def resolve(self, ref: str, *, workspace_scope: str) -> ArtifactRecord:
        return self._load_record(ref, workspace_scope=workspace_scope, verify_blob=True)

    def _load_record(
        self, ref: str, *, workspace_scope: str, verify_blob: bool
    ) -> ArtifactRecord:
        artifact_id = _artifact_id(ref)
        scope = _canonical_workspace_scope(workspace_scope)
        path = self._record_path(scope, artifact_id)
        if not path.is_file():
            raise ArtifactError("artifact 不存在或不属于当前工作区。")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArtifactError("artifact 元数据损坏，无法安全使用。") from exc
        record = self._from_json(raw)
        if record.ref != ref or record.artifact_id != artifact_id:
            raise ArtifactError("artifact 引用与持久化记录不一致。")
        if record.workspace_scope != scope:
            raise ArtifactError("artifact 不属于当前工作区。")
        self._workspace_target(record, requested_scope=scope)
        if verify_blob:
            self._read_blob_verified(record)
        return record

    def read_bytes(self, ref: str, *, workspace_scope: str) -> bytes:
        record = self._load_record(ref, workspace_scope=workspace_scope, verify_blob=False)
        return self._read_blob_verified(record)

    def snapshot(self, ref: str, *, workspace_scope: str) -> ArtifactResolution:
        record = self._load_record(ref, workspace_scope=workspace_scope, verify_blob=True)
        return self._snapshot_record(record)

    def hydrate(
        self, ref: str, *, workspace_scope: str
    ) -> tuple[ArtifactResolution, bytes]:
        """Resolve metadata, verify immutable bytes once, and inspect mutable workspace path."""
        record = self._load_record(ref, workspace_scope=workspace_scope, verify_blob=False)
        data = self._read_blob_verified(record)
        return self._snapshot_record(record), data

    def _snapshot_record(self, record: ArtifactRecord) -> ArtifactResolution:
        target = self._workspace_target(record, requested_scope=record.workspace_scope)
        try:
            current = target.read_bytes()
        except FileNotFoundError:
            return ArtifactResolution(record=record, workspace_path_state="missing")
        except OSError as exc:
            return ArtifactResolution(
                record=record,
                workspace_path_state="unreadable",
                read_error_type=type(exc).__name__,
            )
        current_sha = hashlib.sha256(current).hexdigest()
        state = "current_match" if current_sha == record.sha256 else "current_diverged"
        return ArtifactResolution(
            record=record,
            workspace_path_state=state,
            current_sha256=current_sha,
            current_size_bytes=len(current),
        )

    def _workspace_target(self, record: ArtifactRecord, *, requested_scope: str) -> Path:
        scope = _canonical_workspace_scope(requested_scope)
        if scope != record.workspace_scope:
            raise ArtifactError("artifact 不属于当前工作区。")
        rel = _safe_relative_path(record.relative_path)
        workspace = Path(scope)
        target = (workspace / Path(*rel.parts)).resolve()
        try:
            target.relative_to(workspace)
        except ValueError as exc:
            raise ArtifactError("artifact 持久化路径越出当前工作区。") from exc
        return target

    def _read_blob_verified(self, record: ArtifactRecord) -> bytes:
        path = self._blob_path(record.sha256)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ArtifactError("artifact blob 不可读。") from exc
        if len(data) != record.size_bytes or hashlib.sha256(data).hexdigest() != record.sha256:
            raise ArtifactError("artifact blob 完整性校验失败。")
        return data

    def _record_path(self, scope: str, artifact_id: str) -> Path:
        return self.records_root / _workspace_bucket(scope) / f"{artifact_id}.json"

    def _blob_path(self, digest: str) -> Path:
        return self.blobs_root / digest[:2] / f"{digest}.blob"

    @staticmethod
    def _to_json(record: ArtifactRecord) -> dict[str, Any]:
        return {
            "version": _METADATA_VERSION,
            "artifact_id": record.artifact_id,
            "ref": record.ref,
            "workspace_scope": record.workspace_scope,
            "relative_path": record.relative_path,
            "size_bytes": record.size_bytes,
            "sha256": record.sha256,
            "created_at": record.created_at,
            "owner_session_id": record.owner_session_id,
            "execution_id": record.execution_id,
            "tool_call_id": record.tool_call_id,
            "tool_name": record.tool_name,
            "effect_kind": record.effect_kind,
        }

    @staticmethod
    def _from_json(raw: dict[str, Any]) -> ArtifactRecord:
        try:
            if int(raw.get("version", 0)) != _METADATA_VERSION:
                raise ValueError("unsupported version")
            record = ArtifactRecord(
                artifact_id=str(raw["artifact_id"]),
                ref=str(raw["ref"]),
                workspace_scope=_canonical_workspace_scope(str(raw["workspace_scope"])),
                relative_path=_safe_relative_path(str(raw["relative_path"])).as_posix(),
                size_bytes=int(raw["size_bytes"]),
                sha256=str(raw["sha256"]),
                created_at=float(raw["created_at"]),
                owner_session_id=str(raw.get("owner_session_id") or ""),
                execution_id=str(raw.get("execution_id") or ""),
                tool_call_id=str(raw.get("tool_call_id") or ""),
                tool_name=str(raw.get("tool_name") or ""),
                effect_kind=str(raw.get("effect_kind") or ""),
            )
            if len(record.sha256) != 64:
                raise ValueError("invalid sha256")
            int(record.sha256, 16)
            if record.size_bytes < 0:
                raise ValueError("invalid size")
            if _artifact_id(record.ref) != record.artifact_id:
                raise ValueError("ref mismatch")
            return record
        except (KeyError, TypeError, ValueError, ArtifactError) as exc:
            raise ArtifactError("artifact 元数据字段或路径无效。") from exc
