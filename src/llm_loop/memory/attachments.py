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
    extracted_chars: int = 0
    extracted_sha256: str = ""
    extraction_complete: bool = False
    extraction_kind: str = ""
    page_count: int | None = None
    pages_extracted: int | None = None

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
            "source_text_chars": self.extracted_chars,
            "source_text_sha256": self.extracted_sha256,
            "source_text_complete": self.extraction_complete,
            "source_text_kind": self.extraction_kind,
            "page_count": self.page_count,
            "pages_extracted": self.pages_extracted,
            "hydration_tool": "read_attachment",
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
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        with suppress(OSError):
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        with suppress(OSError):
            tmp.unlink(missing_ok=True)


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
        extracted_text: str = "",
        extraction_complete: bool = False,
        extraction_kind: str = "",
        page_count: int | None = None,
        pages_extracted: int | None = None,
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
        source_text = str(extracted_text or "")
        source_text_sha = (
            hashlib.sha256(source_text.encode("utf-8")).hexdigest() if source_text else ""
        )
        if source_text:
            extracted_path = record_dir / "extracted.txt"
            extracted_path.write_text(source_text, encoding="utf-8")
            with suppress(OSError):
                os.chmod(extracted_path, 0o600)
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
            extracted_chars=len(source_text),
            extracted_sha256=source_text_sha,
            extraction_complete=bool(extraction_complete and source_text),
            extraction_kind=str(extraction_kind or ""),
            page_count=(None if page_count is None else int(page_count)),
            pages_extracted=(None if pages_extracted is None else int(pages_extracted)),
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
            "extracted_chars": record.extracted_chars,
            "extracted_sha256": record.extracted_sha256,
            "extraction_complete": record.extraction_complete,
            "extraction_kind": record.extraction_kind,
            "page_count": record.page_count,
            "pages_extracted": record.pages_extracted,
        }

    @staticmethod
    def _from_json(raw: dict[str, Any]) -> AttachmentRecord:
        try:
            if int(raw.get("version", 0)) != _METADATA_VERSION:
                raise ValueError("unsupported version")
            page_count_raw = raw.get("page_count")
            pages_extracted_raw = raw.get("pages_extracted")
            page_count = None if page_count_raw is None else int(page_count_raw)
            pages_extracted = None if pages_extracted_raw is None else int(pages_extracted_raw)
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
                extracted_chars=max(0, int(raw.get("extracted_chars") or 0)),
                extracted_sha256=str(raw.get("extracted_sha256") or ""),
                extraction_complete=bool(raw.get("extraction_complete", False)),
                extraction_kind=str(raw.get("extraction_kind") or ""),
                page_count=page_count,
                pages_extracted=pages_extracted,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AttachmentError("附件元数据字段无效。") from exc

    def _record_dir(self, record: AttachmentRecord) -> Path:
        return self.root / _workspace_bucket(record.workspace_scope) / record.attachment_id

    def _read_extracted_verified(self, record: AttachmentRecord) -> str | None:
        if not record.extracted_sha256:
            return None
        path = self._record_dir(record) / "extracted.txt"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        if len(text) != record.extracted_chars:
            raise AttachmentError("附件提取文本长度校验失败。")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != record.extracted_sha256:
            raise AttachmentError("附件提取文本完整性校验失败。")
        return text

    def _persist_full_extraction(
        self,
        record: AttachmentRecord,
        text: str,
        *,
        kind: str,
        page_count: int | None,
        coverage_complete: bool,
    ) -> AttachmentRecord:
        record_dir = self._record_dir(record)
        extracted = record_dir / "extracted.txt"
        tmp = record_dir / f".extracted.txt.{uuid.uuid4().hex}.tmp"
        try:
            with tmp.open("w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            with suppress(OSError):
                os.chmod(tmp, 0o600)
            os.replace(tmp, extracted)
        finally:
            with suppress(OSError):
                tmp.unlink(missing_ok=True)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        updated = AttachmentRecord(
            attachment_id=record.attachment_id,
            ref=record.ref,
            workspace_scope=record.workspace_scope,
            filename=record.filename,
            content_type=record.content_type,
            media_type=record.media_type,
            size_bytes=record.size_bytes,
            sha256=record.sha256,
            created_at=record.created_at,
            excerpt=record.excerpt,
            excerpt_kind=record.excerpt_kind,
            extracted_chars=len(text),
            extracted_sha256=digest,
            extraction_complete=bool(text) and bool(coverage_complete),
            extraction_kind=str(kind or "full_text"),
            page_count=(record.page_count if page_count is None else int(page_count)),
            pages_extracted=(
                (record.pages_extracted if record.pages_extracted is not None else 0)
                if not coverage_complete
                else (record.page_count if page_count is None else int(page_count))
            ),
        )
        _atomic_write_json(record_dir / "metadata.json", self._to_json(updated))
        return updated

    def ensure_full_text(self, ref: str, *, workspace_scope: str) -> tuple[AttachmentRecord, str]:
        """Return a complete model-readable text representation when mechanically possible.

        Existing complete extracted text is verified and reused. Legacy or initially
        partial records are re-extracted from the durable original bytes only after an
        explicit hydration request. This is source recovery, not semantic summarization.
        """
        record = self.resolve(ref, workspace_scope=workspace_scope, verify_content=True)
        existing = self._read_extracted_verified(record)
        if existing is not None and record.extraction_complete:
            return record, existing
        try:
            original = self.original_path(ref, workspace_scope=workspace_scope).read_bytes()
        except OSError as exc:
            raise AttachmentError("附件原始内容当前不可读。") from exc
        from llm_loop.web.upload_handlers import extract_full_text

        text, kind, page_count, coverage_complete = extract_full_text(record.filename, original)
        if not text:
            if existing is not None:
                return record, existing
            raise AttachmentError("附件当前没有可读取的文本表示。")
        if kind == "pdf_vision_partial" and not coverage_complete:
            # Current local scan-PDF vision fallback yields one model-readable page.
            # Preserve that mechanical coverage fact rather than pretending all pages
            # were extracted simply because page_count is known.
            record = AttachmentRecord(**{**record.__dict__, "pages_extracted": 1})
        updated = self._persist_full_extraction(
            record,
            text,
            kind=kind,
            page_count=page_count,
            coverage_complete=coverage_complete,
        )
        return updated, text

    def hydrate_text(
        self,
        ref: str,
        *,
        workspace_scope: str,
        offset: int = 0,
        max_chars: int = 100_000,
    ) -> dict[str, Any]:
        """Explicit exact-source hydration with monotonic char paging.

        The upload excerpt budget is intentionally not reused here. Up to 100K chars are
        returned exactly; larger sources expose the next absolute char offset.
        """
        record, text = self.ensure_full_text(ref, workspace_scope=workspace_scope)
        start = max(0, min(int(offset or 0), len(text)))
        width = max(1, min(int(max_chars or 100_000), 100_000))
        chunk = text[start : start + width]
        next_offset = start + len(chunk)
        complete = next_offset >= len(text)
        return {
            "ref": record.ref,
            "filename": record.filename,
            "content_type": record.content_type,
            "media_type": record.media_type,
            "size_bytes": record.size_bytes,
            "sha256": record.sha256,
            "source_text_chars": len(text),
            "source_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "source_text_kind": record.extraction_kind,
            "source_text_complete": record.extraction_complete,
            "offset": start,
            "next_offset": None if complete else next_offset,
            "complete": complete,
            "content": chunk,
        }

    def list_recent(
        self,
        *,
        workspace_scope: str,
        limit: int = 20,
    ) -> tuple[AttachmentRecord, ...]:
        """List recent attachment metadata for one exact workspace.

        Discovery surface only: never returns host paths or extracted bodies.
        A later chat request still resolves/verifies the opaque ref before the
        attachment can enter the request.
        """
        safe_limit = max(1, min(int(limit or 20), 100))
        bucket = self.root / _workspace_bucket(workspace_scope)
        if not bucket.is_dir():
            return ()
        records: list[AttachmentRecord] = []
        try:
            entries = tuple(bucket.iterdir())
        except OSError:
            return ()
        for record_dir in entries:
            if not record_dir.is_dir():
                continue
            metadata_path = record_dir / "metadata.json"
            original_path = record_dir / "original"
            if not metadata_path.is_file() or not original_path.is_file():
                continue
            try:
                raw = json.loads(metadata_path.read_text(encoding="utf-8"))
                record = self._from_json(raw)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if record.workspace_scope != workspace_scope:
                continue
            if record.ref != f"{ATTACHMENT_SCHEME}{record.attachment_id}":
                continue
            records.append(record)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return tuple(records[:safe_limit])

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
