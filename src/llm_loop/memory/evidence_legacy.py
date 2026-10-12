"""Legacy sidecar migration and Evidence lifecycle helpers.

Phase 6 intentionally treats old ``data/audit/{tool_outputs,cmd_outputs}`` files as
untrusted, unowned bytes.  A file becomes model-visible Evidence only when a persisted
session tool result proves ownership mechanically:

* the tool result explicitly references the sidecar path;
* the path is a regular, non-symlink ``.log`` inside one of the two legacy directories;
* the deterministic filename digest matches the exact bytes;
* the truncation marker's total/head/tail claims match the exact sidecar text; and
* the visible tool result actually contains the claimed head and tail bytes.

Files that fail or lack that proof remain in place and are recorded only in a quarantine
inventory.  The inventory is never part of the Evidence ledger/search surface.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from llm_loop.memory.evidence import (
    BlobStore,
    Coverage,
    EvidenceCapture,
    EvidenceLedgerStore,
    OwnerScope,
    Provenance,
    SourceIdentity,
    SourceKind,
    SourceVersionPolicy,
    _file_lock,
    make_capture_request,
)

_MARKER_RE = re.compile(
    r"\[输出已截断\]\s*完整\s*(?P<total>\d+)\s*字符，"
    r"仅首\s*(?P<head>\d+)\s*\+\s*尾\s*(?P<tail>\d+)"
)
# Accept both pre-agency legacy wording and the current truthful durable-dump marker.
# The migrator is historical compatibility; it must not force current tool output to
# keep obsolete prompt guidance merely so old parser regexes continue to match.
_PATH_RE = re.compile(
    r"(?:read_file\s+读取落盘全文\s+|完整原文已落盘:\s*)"
    r"(?P<path>.+?\.log)(?=。|；|$)"
)
_DIGEST_NAME_RE = re.compile(r"^(?P<digest>[0-9a-f]{16})_")


@dataclass(frozen=True, slots=True)
class LegacyMigrationReport:
    scanned_files: int
    migrated_records: int
    reused_records: int
    quarantined_files: int
    rejected_references: int
    inventory_path: Path


@dataclass(frozen=True, slots=True)
class EvidenceDeleteReport:
    records_removed: int
    blobs_deleted: int
    blobs_retained: int


@dataclass(frozen=True, slots=True)
class _Proof:
    path: Path
    content: str
    digest: str


class EvidenceLifecycle:
    """Delete logical owner state first; collect immutable blobs only at refcount zero."""

    def __init__(self, blobs: BlobStore, ledger: EvidenceLedgerStore) -> None:
        self.blobs = blobs
        self.ledger = ledger

    def delete_owner(self, owner: OwnerScope) -> EvidenceDeleteReport:
        with _file_lock(self.ledger.root / ".gc.lock"):
            removed = self.ledger.remove_owner(owner)
            unique = {blob.ref: blob for blob in removed}
            deleted = 0
            retained = 0
            for blob in unique.values():
                if self.ledger.blob_refcount(blob) > 0:
                    retained += 1
                    continue
                if self.blobs.delete(blob):
                    deleted += 1
            return EvidenceDeleteReport(
                records_removed=len(removed),
                blobs_deleted=deleted,
                blobs_retained=retained,
            )


    def delete_session(self, session_id: str) -> EvidenceDeleteReport:
        total_records = 0
        total_deleted = 0
        total_retained = 0
        for owner in self.ledger.owners_for_session(session_id):
            report = self.delete_owner(owner)
            total_records += report.records_removed
            total_deleted += report.blobs_deleted
            total_retained += report.blobs_retained
        return EvidenceDeleteReport(
            records_removed=total_records,
            blobs_deleted=total_deleted,
            blobs_retained=total_retained,
        )


class LegacySidecarMigrator:
    """Owner-proof migration for deterministic legacy truncation sidecars."""

    def __init__(
        self,
        *,
        data_dir: str | Path,
        sessions: Any,
        capture: EvidenceCapture,
        ledger: EvidenceLedgerStore,
        workspace_id: str,
    ) -> None:
        workspace = Path(workspace_id).expanduser().absolute()
        data = Path(data_dir).expanduser()
        if not data.is_absolute():
            data = workspace / data
        self.data_dir = data.absolute()
        self.sessions = sessions
        self.capture = capture
        self.ledger = ledger
        self.workspace_id = str(workspace)
        self._roots = (
            self.data_dir / "audit" / "tool_outputs",
            self.data_dir / "audit" / "cmd_outputs",
        )
        self.inventory_path = self.data_dir / "evidence" / "quarantine" / "legacy_sidecars.json"

    def migrate_all(self) -> LegacyMigrationReport:
        sidecars = self._scan_sidecars()
        owned_paths: set[Path] = set()
        failure_reason: dict[Path, str] = {}
        migrated = 0
        reused = 0
        rejected = 0

        for meta in self.sessions.list_sessions(include_archived=True):
            session_id = str(meta.session_id)
            try:
                sess = self.sessions.load(session_id)
            except Exception:  # noqa: BLE001 - unreadable session cannot prove ownership
                continue
            owner = OwnerScope(workspace_id=self.workspace_id, session_id=session_id)
            for index, message in enumerate(sess.messages):
                if message.role != "tool" or "[输出已截断]" not in (message.content or ""):
                    continue
                raw_path = self._extract_path(message.content)
                if raw_path is None:
                    continue
                candidate = self._normalize_candidate(raw_path)
                proof, reason = self._prove(message.content, candidate)
                if proof is None:
                    rejected += 1
                    if candidate in sidecars:
                        failure_reason[candidate] = reason
                    continue

                stable_id = self._stable_capture_id(
                    message_index=index,
                    tool_call_id=message.tool_call_id,
                    message_ts=float(message.ts or 0.0),
                    digest=proof.digest,
                )
                acquired_at = self._acquired_at(float(message.ts or 0.0), proof.path)
                before = self.ledger.count(owner)
                self.capture.capture(
                    make_capture_request(
                        owner=owner,
                        stable_capture_id=stable_id,
                        raw_observation=proof.content,
                        acquired_at=acquired_at,
                        tool_name=message.tool_name or "legacy_sidecar",
                        tool_call_id=message.tool_call_id,
                        source=SourceIdentity(
                            kind=SourceKind.CONVERSATION,
                            locator=f"legacy-sidecar:{proof.path.name}",
                            version_policy=SourceVersionPolicy.SNAPSHOT_ONLY,
                        ),
                        coverage=Coverage(
                            unit="legacy_tool_observation",
                            start=0,
                            end_exclusive=len(proof.content),
                            source_complete=True,
                        ),
                        provenance=Provenance(
                            producer="legacy_sidecar_migration",
                            authority="persisted_tool_result",
                            scope=message.tool_name or "tool",
                        ),
                    )
                )
                after = self.ledger.count(owner)
                if after > before:
                    migrated += 1
                else:
                    reused += 1
                owned_paths.add(proof.path)

        quarantine = self._quarantine_rows(sidecars, owned_paths, failure_reason)
        self._write_inventory(quarantine)
        return LegacyMigrationReport(
            scanned_files=len(sidecars),
            migrated_records=migrated,
            reused_records=reused,
            quarantined_files=len(quarantine),
            rejected_references=rejected,
            inventory_path=self.inventory_path,
        )

    def _scan_sidecars(self) -> set[Path]:
        out: set[Path] = set()
        for root in self._roots:
            if not root.exists():
                continue
            for path in root.iterdir():
                if path.suffix == ".log" and (path.is_file() or path.is_symlink()):
                    out.add(path.absolute())
        return out

    @staticmethod
    def _extract_path(content: str) -> str | None:
        match = _PATH_RE.search(content)
        if match is None:
            return None
        return match.group("path").strip()

    def _normalize_candidate(self, raw: str) -> Path:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = Path(self.workspace_id) / candidate
        return candidate.absolute()

    def _prove(self, projected: str, path: Path) -> tuple[_Proof | None, str]:
        if path.suffix != ".log":
            return None, "not_log"
        allowed = any(path.parent == root.absolute() for root in self._roots)
        if not allowed:
            return None, "outside_legacy_roots"
        if path.is_symlink():
            return None, "symlink"
        if not path.is_file():
            return None, "missing"

        name_match = _DIGEST_NAME_RE.match(path.name)
        if name_match is None:
            return None, "filename_digest_missing"
        marker = _MARKER_RE.search(projected)
        if marker is None:
            return None, "marker_unparseable"
        try:
            full = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None, "unreadable"
        digest = hashlib.sha256(full.encode("utf-8")).hexdigest()
        if digest[:16] != name_match.group("digest"):
            return None, "filename_digest_mismatch"

        total = int(marker.group("total"))
        head = int(marker.group("head"))
        tail = int(marker.group("tail"))
        if len(full) != total:
            return None, "total_mismatch"
        if head < 0 or tail < 0 or head + tail > len(full):
            return None, "range_invalid"
        if head and not projected.startswith(full[:head]):
            return None, "head_mismatch"
        if tail and not projected.endswith(full[-tail:]):
            return None, "tail_mismatch"
        return _Proof(path=path, content=full, digest=digest), ""

    @staticmethod
    def _stable_capture_id(
        *, message_index: int, tool_call_id: str | None, message_ts: float, digest: str
    ) -> str:
        identity = tool_call_id or f"idx={message_index};ts={message_ts:.9f}"
        return f"legacy-sidecar:{identity}:{digest}"

    @staticmethod
    def _acquired_at(message_ts: float, path: Path) -> datetime:
        if message_ts > 0:
            return datetime.fromtimestamp(message_ts, UTC)
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, UTC)
        except OSError:
            return datetime.fromtimestamp(0, UTC)

    def _quarantine_rows(
        self,
        sidecars: set[Path],
        owned_paths: set[Path],
        failure_reason: dict[Path, str],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for path in sorted(sidecars, key=lambda p: str(p)):
            if path in owned_paths:
                continue
            reason = failure_reason.get(path)
            if reason is None:
                reason = "symlink" if path.is_symlink() else "unreferenced"
            elif reason not in {"symlink", "unreferenced"}:
                reason = f"proof_failed:{reason}"
            sha256 = ""
            size_bytes = 0
            inventory_error = ""
            try:
                size_bytes = path.lstat().st_size
                if not path.is_symlink() and path.is_file():
                    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                inventory_error = type(exc).__name__
                if reason == "unreferenced":
                    reason = "unreadable"
            try:
                display_path = str(path.relative_to(self.data_dir))
            except ValueError:
                display_path = str(path)
            rows.append(
                {
                    "path": display_path,
                    "reason": reason,
                    "sha256": sha256,
                    "size_bytes": size_bytes,
                    "inventory_error": inventory_error,
                    "model_visible": False,
                }
            )
        return rows

    def _write_inventory(self, rows: list[dict[str, object]]) -> None:
        self.inventory_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "legacy-sidecar-quarantine/v1",
            "policy": "inventory-only; never Evidence/model-visible without owner proof",
            "items": rows,
        }
        tmp = self.inventory_path.with_name(f".{self.inventory_path.name}.{uuid4().hex}.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, self.inventory_path)
