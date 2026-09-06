"""Durable Web attachment references.

The client only sees opaque ``attachment://<id>`` references. Host filesystem paths
never enter the request/response contract. Records are scoped to the workspace that
was active when the upload was accepted and live under ``<data_dir>/attachments``.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ATTACHMENT_SCHEME = "attachment://"
ATTACHMENT_EXCERPT_CHARS = 2_000
_ATTACHMENT_ID_LEN = 32
_METADATA_VERSION = 1


class AttachmentError(ValueError):
    """A client-visible attachment reference cannot be resolved truthfully."""


@dataclass(frozen=True)
class AttachmentRecord:
    attachment_id: str
    ref: str
    workspace_scope: str
    filename: str
    content_type: str
    media_type: str
    size_bytes: int
    sha256: str
    created_at: float
    excerpt: str = ""
    excerpt_kind: str = ""

    def public_facts(self) -> dict[str, Any]:
        """Facts safe to persist in Message.metadata / return to Web clients."""
        return {
            "ref": self.ref,
            "filename": self.filename,
            "content_type": self.content_type,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "created_at": self.created_at,
            "excerpt": self.excerpt,
            "excerpt_kind": self.excerpt_kind,
        }


def workspace_scope(root: str | Path | None) -> str:
    """Canonical mechanical workspace identity used for attachment ownership."""
    raw = Path(root).expanduser() if root else Path.cwd()
    return str(raw.resolve())


def _workspace_bucket(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:32]


def _attachment_id(ref: str) -> str:
    if not isinstance(ref, str) or not ref.startswith(ATTACHMENT_SCHEME):
        raise AttachmentError("附件引用格式无效。")
    attachment_id = ref[len(ATTACHMENT_SCHEME) :]
    if len(attachment_id) != _ATTACHMENT_ID_LEN:
        raise AttachmentError("附件引用格式无效。")
    try:
        int(attachment_id, 16)
    except ValueError as exc:
        raise AttachmentError("附件引用格式无效。") from exc
    return attachment_id


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    tmp.write_text(text, encoding="utf-8")
    with suppress(OSError):
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class AttachmentStore:
    """Workspace-scoped durable bytes + metadata store for Web uploads."""

    def __init__(self, data_dir: str | Path) -> None:
        self.root = Path(data_dir).expanduser().resolve() / "attachments"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            os.chmod(self.root, 0o700)

    def create(
        self,
        *,
        workspace_scope: str,
        filename: str,
        data: bytes,
        content_type: str,
        excerpt: str = "",
        excerpt_kind: str = "",
    ) -> AttachmentRecord:
        attachment_id = uuid.uuid4().hex
        ref = f"{ATTACHMENT_SCHEME}{attachment_id}"
        bucket = self.root / _workspace_bucket(workspace_scope)
        bucket.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            os.chmod(bucket, 0o700)
        record_dir = bucket / attachment_id
        record_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
        with suppress(OSError):
            os.chmod(record_dir, 0o700)

        original = record_dir / "original"
        original.write_bytes(data)
        with suppress(OSError):
            os.chmod(original, 0o600)

        safe_excerpt = str(excerpt or "")[:ATTACHMENT_EXCERPT_CHARS]
        record = AttachmentRecord(
            attachment_id=attachment_id,
            ref=ref,
            workspace_scope=workspace_scope,
            filename=str(filename),
            content_type=str(content_type or "file"),
            media_type=mimetypes.guess_type(str(filename))[0] or "application/octet-stream",
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            created_at=time.time(),
            excerpt=safe_excerpt,
            excerpt_kind=str(excerpt_kind or ""),
        )
        _atomic_write_json(record_dir / "metadata.json", self._to_json(record))
        return record

    def resolve(
        self,
        ref: str,
        *,
        workspace_scope: str,
        verify_content: bool = True,
    ) -> AttachmentRecord:
        attachment_id = _attachment_id(ref)
        record_dir = self.root / _workspace_bucket(workspace_scope) / attachment_id
        metadata_path = record_dir / "metadata.json"
        original = record_dir / "original"
        if not metadata_path.is_file() or not original.is_file():
            raise AttachmentError("附件不存在或不属于当前工作区。")
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AttachmentError("附件元数据损坏，无法安全使用。") from exc
        record = self._from_json(raw)
        if record.ref != ref or record.attachment_id != attachment_id:
            raise AttachmentError("附件引用与持久化记录不一致。")
        if record.workspace_scope != workspace_scope:
            raise AttachmentError("附件不属于当前工作区。")
        if verify_content:
            try:
                data = original.read_bytes()
            except OSError as exc:
                raise AttachmentError("附件原始内容不可读。") from exc
            if len(data) != record.size_bytes:
                raise AttachmentError("附件大小校验失败。")
            if hashlib.sha256(data).hexdigest() != record.sha256:
                raise AttachmentError("附件完整性校验失败。")
        return record

    @staticmethod
    def _to_json(record: AttachmentRecord) -> dict[str, Any]:
        return {
            "version": _METADATA_VERSION,
            "attachment_id": record.attachment_id,
            "ref": record.ref,
            "workspace_scope": record.workspace_scope,
            "filename": record.filename,
            "content_type": record.content_type,
            "media_type": record.media_type,
            "size_bytes": record.size_bytes,
            "sha256": record.sha256,
            "created_at": record.created_at,
            "excerpt": record.excerpt,
            "excerpt_kind": record.excerpt_kind,
        }

    @staticmethod
    def _from_json(raw: dict[str, Any]) -> AttachmentRecord:
        try:
            if int(raw.get("version", 0)) != _METADATA_VERSION:
                raise ValueError("unsupported version")
            return AttachmentRecord(
                attachment_id=str(raw["attachment_id"]),
                ref=str(raw["ref"]),
                workspace_scope=str(raw["workspace_scope"]),
                filename=str(raw["filename"]),
                content_type=str(raw["content_type"]),
                media_type=str(raw.get("media_type") or "application/octet-stream"),
                size_bytes=int(raw["size_bytes"]),
                sha256=str(raw["sha256"]),
                created_at=float(raw["created_at"]),
                excerpt=str(raw.get("excerpt") or "")[:ATTACHMENT_EXCERPT_CHARS],
                excerpt_kind=str(raw.get("excerpt_kind") or ""),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AttachmentError("附件元数据字段无效。") from exc

    def original_path(self, ref: str, *, workspace_scope: str) -> Path:
        """Internal-only path helper. Callers must resolve/verify the record first."""
        record = self.resolve(ref, workspace_scope=workspace_scope, verify_content=True)
        return self.root / _workspace_bucket(workspace_scope) / record.attachment_id / "original"


__all__ = [
    "ATTACHMENT_EXCERPT_CHARS",
    "ATTACHMENT_SCHEME",
    "AttachmentError",
    "AttachmentRecord",
    "AttachmentStore",
    "workspace_scope",
]
