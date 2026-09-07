"""Mechanical authenticity checks for Evidence refs recorded by TaskStore.

This module deliberately answers only whether already-declared Evidence refs can be
resolved inside the current trusted owner scope and whether their immutable blobs are
still intact. It never refreshes source freshness and never judges relevance,
sufficiency, acceptance, or task completion.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from llm_loop.memory.evidence import (
    BlobStore,
    EvidenceAuthDeniedError,
    EvidenceBlobLostError,
    EvidenceCorruptedError,
    EvidenceLedgerStore,
    EvidenceRef,
    EvidenceRefUnknownError,
    OwnerScope,
)
from llm_loop.memory.evidence import _file_lock as _evidence_file_lock


@dataclass(frozen=True, slots=True)
class TaskEvidenceVerificationReport:
    status: str
    checked_at: str
    refs_digest: str
    checked_count: int
    failing_ref: str = ""


class TaskEvidenceVerificationError(ValueError):
    def __init__(self, status: str, *, failing_ref: str = "") -> None:
        self.status = status
        self.failing_ref = failing_ref
        suffix = f" ref={failing_ref}" if failing_ref else ""
        super().__init__(f"evidence verification failed: status={status}{suffix}")


class TaskEvidenceVerifier:
    """Read-only owner/integrity verifier over the existing Evidence stores."""

    def __init__(
        self,
        blobs: BlobStore,
        ledger: EvidenceLedgerStore,
        *,
        owner_resolver: Callable[[], OwnerScope],
    ) -> None:
        self._blobs = blobs
        self._ledger = ledger
        self._owner_resolver = owner_resolver

    def verify(self, refs: Sequence[str]) -> TaskEvidenceVerificationReport:
        normalized = [str(ref).strip() for ref in refs]
        digest = _refs_digest(normalized)
        checked_at = datetime.now(UTC).isoformat()

        parsed: list[EvidenceRef] = []
        for raw in normalized:
            try:
                parsed.append(EvidenceRef(raw))
            except (TypeError, ValueError):
                return TaskEvidenceVerificationReport(
                    status="unsupported_ref",
                    checked_at=checked_at,
                    refs_digest=digest,
                    checked_count=len(parsed),
                    failing_ref=raw,
                )

        try:
            owner = self._owner_resolver()
        except Exception:  # noqa: BLE001
            return TaskEvidenceVerificationReport(
                status="verification_unavailable",
                checked_at=checked_at,
                refs_digest=digest,
                checked_count=0,
                failing_ref=(normalized[0] if normalized else ""),
            )

        try:
            with _evidence_file_lock(self._ledger.root / ".gc.lock"):
                for index, evidence_ref in enumerate(parsed):
                    try:
                        record = self._ledger.require_authorized(owner, evidence_ref)
                    except (EvidenceAuthDeniedError, EvidenceRefUnknownError):
                        return TaskEvidenceVerificationReport(
                            status="unresolved_or_not_authorized",
                            checked_at=checked_at,
                            refs_digest=digest,
                            checked_count=index,
                            failing_ref=evidence_ref.ref,
                        )
                    try:
                        self._blobs.read_text(record.blob_ref)
                    except EvidenceBlobLostError:
                        return TaskEvidenceVerificationReport(
                            status="blob_missing",
                            checked_at=checked_at,
                            refs_digest=digest,
                            checked_count=index,
                            failing_ref=evidence_ref.ref,
                        )
                    except EvidenceCorruptedError:
                        return TaskEvidenceVerificationReport(
                            status="integrity_failed",
                            checked_at=checked_at,
                            refs_digest=digest,
                            checked_count=index,
                            failing_ref=evidence_ref.ref,
                        )
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return TaskEvidenceVerificationReport(
                status="verification_unavailable",
                checked_at=checked_at,
                refs_digest=digest,
                checked_count=0,
                failing_ref=(normalized[0] if normalized else ""),
            )

        return TaskEvidenceVerificationReport(
            status="verified",
            checked_at=checked_at,
            refs_digest=digest,
            checked_count=len(parsed),
        )


def _refs_digest(refs: Sequence[str]) -> str:
    raw = json.dumps(list(refs), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
