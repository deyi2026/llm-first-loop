"""Authenticated-human file operations over the shared mechanical FileService."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from llm_loop.event_log.model import (
    EVENT_HUMAN_FILE_EDIT_OBSERVED,
    EVENT_HUMAN_FILE_EDIT_PREPARED,
    EVENT_HUMAN_FILE_EDIT_REJECTED,
)
from llm_loop.tools.safety import link_shaped_paths
from llm_loop.workspace.artifacts import ARTIFACT_SCHEME, ArtifactError
from llm_loop.workspace.file_effect_query import FileEffectQueryService
from llm_loop.workspace.file_effects import FileEffectReceipt, FileEffectSink
from llm_loop.workspace.file_service import (
    FILE_CONTRACT_VERSION,
    UTF8_BOM,
    FileObservation,
    FileService,
    FileServiceError,
)


class HumanFileOperationError(ValueError):
    def __init__(self, code: str, *, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f"{code}: {detail}")


class _HumanFileEffectSink(FileEffectSink):
    def __init__(
        self,
        *,
        event_store: Any,
        session_id: str,
        workspace_scope: str,
        relative_path: str,
        operation_id: str,
        request_id: str,
        request_sha256: str,
        expected_snapshot_ref: str,
    ) -> None:
        self.event_store = event_store
        self.owner_session_id = session_id
        self.workspace_scope = str(Path(workspace_scope).resolve())
        self.relative_path = relative_path
        self.operation_id = operation_id
        self.request_id = request_id
        self.request_sha256 = request_sha256
        self.expected_snapshot_ref = expected_snapshot_ref
        self.tool_call_id = ""
        self.tool_name = ""
        self.effect_kind = "file_replace"

    @property
    def records_durable(self) -> bool:
        return bool(getattr(self.event_store, "enabled", False))

    def prepared(self, *, canonical_path: Path, before_bytes: bytes, expected_after_bytes: bytes) -> bool:
        if not self.records_durable:
            return False
        event = self.event_store.append(
            self.owner_session_id,
            EVENT_HUMAN_FILE_EDIT_PREPARED,
            {
                "operation_id": self.operation_id,
                "request_id": self.request_id,
                "request_sha256": self.request_sha256,
                "origin": "authenticated_user",
                "workspace_root": self.workspace_scope,
                "relative_path": self.relative_path,
                "before_sha256": hashlib.sha256(before_bytes).hexdigest(),
                "before_size": len(before_bytes),
                "expected_after_sha256": hashlib.sha256(expected_after_bytes).hexdigest(),
                "expected_after_size": len(expected_after_bytes),
                "expected_snapshot_ref": self.expected_snapshot_ref,
                "precondition_checked": True,
                "file_contract_version": FILE_CONTRACT_VERSION,
            },
        )
        return event is not None

    def observed(
        self,
        *,
        canonical_path: Path,
        actual_after_bytes: bytes,
        expected_after_bytes: bytes,
        actual_mtime_ns: int | None,
        artifact_ref: str,
    ) -> bool:
        if not self.records_durable:
            return False
        actual_sha = hashlib.sha256(actual_after_bytes).hexdigest()
        expected_sha = hashlib.sha256(expected_after_bytes).hexdigest()
        event = self.event_store.append(
            self.owner_session_id,
            EVENT_HUMAN_FILE_EDIT_OBSERVED,
            {
                "operation_id": self.operation_id,
                "request_id": self.request_id,
                "origin": "authenticated_user",
                "workspace_root": self.workspace_scope,
                "relative_path": self.relative_path,
                "actual_after_sha256": actual_sha,
                "actual_size": len(actual_after_bytes),
                "actual_mtime_ns": actual_mtime_ns,
                "matches_expected": actual_sha == expected_sha,
                "artifact_ref": artifact_ref,
                "receipt_state": "recorded",
            },
        )
        return event is not None


class HumanFileOperationService:
    """Thin human operation authority: auth identity is supplied by the Web/CLI entry."""

    def __init__(
        self,
        *,
        session_store: Any,
        event_store: Any,
        file_service: FileService,
        query_service: FileEffectQueryService,
        max_file_bytes: int = 1024 * 1024,
    ) -> None:
        self.session_store = session_store
        self.event_store = event_store
        self.file_service = file_service
        self.query_service = query_service
        self.max_file_bytes = max(1, int(max_file_bytes))

    @staticmethod
    def _scope(workspace_scope: str) -> str:
        return str(Path(workspace_scope).expanduser().resolve())

    def _path(self, workspace_scope: str, relative_path: str) -> tuple[Path, str]:
        raw = str(relative_path or "")
        if not raw or "\\" in raw:
            raise HumanFileOperationError("invalid_path")
        rel = PurePosixPath(raw)
        if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
            raise HumanFileOperationError("invalid_path")
        scope = Path(self._scope(workspace_scope))
        target = scope.joinpath(*rel.parts)
        probe = link_shaped_paths(target)
        if probe.status == "links_found":
            raise HumanFileOperationError("symlink_forbidden")
        if probe.status == "probe_failed":
            raise HumanFileOperationError("path_probe_failed")
        try:
            resolved = target.resolve()
            resolved.relative_to(scope)
        except (OSError, ValueError) as exc:
            raise HumanFileOperationError("out_of_bounds") from exc
        if not resolved.is_file():
            raise HumanFileOperationError("file_not_found")
        return resolved, rel.as_posix()

    def _require_session(self, session_id: str) -> None:
        try:
            exists = self.session_store.exists(session_id)
        except Exception as exc:  # owner mismatch/deleted stays fail-closed
            raise HumanFileOperationError("session_unavailable", detail=type(exc).__name__) from exc
        if not exists:
            raise HumanFileOperationError("session_not_found")

    def assert_session_available(self, session_id: str) -> None:
        self._require_session(session_id)

    def observe(
        self,
        *,
        session_id: str,
        workspace_scope: str,
        relative_path: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> FileObservation:
        self._require_session(session_id)
        target, rel = self._path(workspace_scope, relative_path)
        from llm_loop.workspace.file_effects import FileArtifactProvenance

        try:
            return self.file_service.observe(
                path=target,
                workspace_scope=self._scope(workspace_scope),
                provenance=FileArtifactProvenance(
                    workspace_scope=self._scope(workspace_scope),
                    owner_session_id=session_id,
                    operation_id=f"human-observe-{uuid.uuid4().hex}",
                    effect_kind="file_observation",
                ),
                offset=offset,
                limit=limit,
                max_bytes=self.max_file_bytes,
                strict_utf8=True,
                strip_utf8_bom=True,
            )
        except FileServiceError as exc:
            code = {
                "UnsupportedTextEncoding": "unsupported_text_encoding",
                "ResourceLimitExceeded": "file_too_large",
                "FileNotFoundError": "file_not_found",
            }.get(exc.error_type, exc.error_type.lower())
            raise HumanFileOperationError(code, detail=exc.detail) from exc

    def request_digest(
        self,
        *,
        session_id: str,
        workspace_scope: str,
        relative_path: str,
        expected_snapshot_ref: str,
        content: str,
        file_contract_version: int,
    ) -> str:
        body = {
            "session_id": str(session_id),
            "workspace_scope": self._scope(workspace_scope),
            "path": str(relative_path),
            "expected_snapshot_ref": str(expected_snapshot_ref),
            "content_sha256": hashlib.sha256(str(content).encode("utf-8")).hexdigest(),
            "file_contract_version": int(file_contract_version),
        }
        raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _existing_request(self, session_id: str, workspace_scope: str, request_id: str):
        scope = self._scope(workspace_scope)
        matched = []
        for event in self.event_store.read(session_id):
            if event.type not in {
                EVENT_HUMAN_FILE_EDIT_PREPARED,
                EVENT_HUMAN_FILE_EDIT_OBSERVED,
                EVENT_HUMAN_FILE_EDIT_REJECTED,
            }:
                continue
            if str(event.payload.get("request_id") or "") != request_id:
                continue
            try:
                event_scope = self._scope(str(event.payload.get("workspace_root") or ""))
            except Exception:
                continue
            if event_scope == scope:
                matched.append(event)
        return matched

    def _receipt_for_existing(self, session_id: str, workspace_scope: str, events: list[Any]) -> FileEffectReceipt:
        rejected = next(
            (event for event in reversed(events) if event.type == EVENT_HUMAN_FILE_EDIT_REJECTED),
            None,
        )
        if rejected is not None:
            raise HumanFileOperationError(str(rejected.payload.get("reason") or "request_rejected"))
        op = next((str(e.payload.get("operation_id") or "") for e in events if e.payload.get("operation_id")), "")
        page = self.query_service.query(
            session_id=session_id,
            workspace_scope=workspace_scope,
            query=f"operation:{op}",
            limit=1,
        )
        if page.receipts:
            return page.receipts[0]
        raise HumanFileOperationError("operation_unavailable")

    def _record_rejected(
        self,
        *,
        session_id: str,
        workspace_scope: str,
        relative_path: str,
        operation_id: str,
        request_id: str,
        request_sha256: str,
        reason: str,
        precondition_checked: bool,
    ) -> None:
        if not bool(getattr(self.event_store, "enabled", False)):
            return
        self.event_store.append(
            session_id,
            EVENT_HUMAN_FILE_EDIT_REJECTED,
            {
                "operation_id": operation_id,
                "request_id": request_id,
                "request_sha256": request_sha256,
                "origin": "authenticated_user",
                "workspace_root": self._scope(workspace_scope),
                "relative_path": relative_path,
                "reason": reason,
                "precondition_checked": precondition_checked,
                "file_contract_version": FILE_CONTRACT_VERSION,
            },
        )

    def edit(
        self,
        *,
        session_id: str,
        workspace_scope: str,
        request_id: str,
        relative_path: str,
        expected_snapshot_ref: str,
        content: str,
        file_contract_version: int = FILE_CONTRACT_VERSION,
    ) -> FileEffectReceipt:
        self._require_session(session_id)
        if file_contract_version != FILE_CONTRACT_VERSION:
            raise HumanFileOperationError("unsupported_file_contract")
        if not expected_snapshot_ref.startswith(ARTIFACT_SCHEME):
            raise HumanFileOperationError("invalid_snapshot_ref")
        if len(content.encode("utf-8")) > self.max_file_bytes:
            raise HumanFileOperationError("file_too_large")
        target, rel = self._path(workspace_scope, relative_path)
        digest = self.request_digest(
            session_id=session_id,
            workspace_scope=workspace_scope,
            relative_path=rel,
            expected_snapshot_ref=expected_snapshot_ref,
            content=content,
            file_contract_version=file_contract_version,
        )
        existing = self._existing_request(session_id, workspace_scope, request_id)
        if existing:
            old_digest = next((str(e.payload.get("request_sha256") or "") for e in existing if e.payload.get("request_sha256")), "")
            if old_digest and old_digest != digest:
                raise HumanFileOperationError("request_conflict")
            return self._receipt_for_existing(session_id, workspace_scope, existing)

        with self.session_store.run_lease(session_id) as acquired:
            if not acquired:
                raise HumanFileOperationError("session_busy")
            existing = self._existing_request(session_id, workspace_scope, request_id)
            if existing:
                old_digest = next((str(e.payload.get("request_sha256") or "") for e in existing if e.payload.get("request_sha256")), "")
                if old_digest and old_digest != digest:
                    raise HumanFileOperationError("request_conflict")
                return self._receipt_for_existing(session_id, workspace_scope, existing)
            operation_id = uuid.uuid4().hex
            if not bool(getattr(self.event_store, "enabled", False)):
                raise HumanFileOperationError("recording_unavailable")
            store = self.file_service.artifact_store
            if store is None:
                raise HumanFileOperationError("snapshot_unavailable")
            try:
                resolution, expected_bytes = store.hydrate(
                    expected_snapshot_ref, workspace_scope=self._scope(workspace_scope)
                )
            except ArtifactError as exc:
                self._record_rejected(
                    session_id=session_id,
                    workspace_scope=workspace_scope,
                    relative_path=rel,
                    operation_id=operation_id,
                    request_id=request_id,
                    request_sha256=digest,
                    reason="invalid_snapshot_ref",
                    precondition_checked=False,
                )
                raise HumanFileOperationError("invalid_snapshot_ref") from exc
            if resolution.record.relative_path != rel:
                self._record_rejected(
                    session_id=session_id,
                    workspace_scope=workspace_scope,
                    relative_path=rel,
                    operation_id=operation_id,
                    request_id=request_id,
                    request_sha256=digest,
                    reason="invalid_snapshot_ref",
                    precondition_checked=False,
                )
                raise HumanFileOperationError("invalid_snapshot_ref")
            probe = expected_bytes[len(UTF8_BOM) :] if expected_bytes.startswith(UTF8_BOM) else expected_bytes
            try:
                old_text = probe.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise HumanFileOperationError("unsupported_text_encoding") from exc
            sink = _HumanFileEffectSink(
                event_store=self.event_store,
                session_id=session_id,
                workspace_scope=workspace_scope,
                relative_path=rel,
                operation_id=operation_id,
                request_id=request_id,
                request_sha256=digest,
                expected_snapshot_ref=expected_snapshot_ref,
            )
            try:
                result = self.file_service.edit(
                    path=target,
                    old_string=old_text,
                    new_string=content,
                    effect_sink=sink,
                    workspace_scope=self._scope(workspace_scope),
                    expected_snapshot_ref=expected_snapshot_ref,
                    whole_file=True,
                )
            except FileServiceError as exc:
                if exc.error_type in {"VersionConflict", "VersionPreconditionInvalid"}:
                    reason = "version_conflict" if exc.error_type == "VersionConflict" else "invalid_snapshot_ref"
                    self._record_rejected(
                        session_id=session_id,
                        workspace_scope=workspace_scope,
                        relative_path=rel,
                        operation_id=operation_id,
                        request_id=request_id,
                        request_sha256=digest,
                        reason=reason,
                        precondition_checked=exc.error_type == "VersionConflict",
                    )
                    raise HumanFileOperationError(reason) from exc
                code = {
                    "EffectPreparedUnavailable": "recording_unavailable",
                    "PathLockUnavailable": "path_lock_unavailable",
                }.get(exc.error_type, exc.error_type.lower())
                raise HumanFileOperationError(code, detail=exc.detail) from exc

            actual_sha = hashlib.sha256(result.actual_after_bytes or b"").hexdigest()
            expected_sha = hashlib.sha256(result.expected_after_bytes).hexdigest()
            return FileEffectReceipt(
                operation_id=operation_id,
                origin="authenticated_user",
                path=rel,
                before_sha256=hashlib.sha256(result.source_bytes).hexdigest(),
                expected_after_sha256=expected_sha,
                observed_after_sha256=actual_sha,
                artifact_ref=(str(result.artifact_fact.get("artifact_ref") or "") if result.artifact_fact else ""),
                effect_state="observed_match" if actual_sha == expected_sha else "observed_mismatch",
                receipt_state=result.receipt_state,
                precondition_checked=result.precondition_checked,
                causation_proven=True,
            )
