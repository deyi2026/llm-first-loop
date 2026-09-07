"""Mechanical file-effect identities and adapter contracts.

The workspace layer owns byte/path/version facts only. Event identity stays with the
caller: model-tool operations adapt ToolExecutionJournal; authenticated-human operations adapt EventStore. Nothing here creates model, user, task, or completion authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FileArtifactProvenance:
    """Mechanical provenance used when an exact file snapshot is materialized."""

    workspace_scope: str
    owner_session_id: str
    operation_id: str
    tool_call_id: str = ""
    tool_name: str = ""
    effect_kind: str = "file_observation"


class FileEffectSink(Protocol):
    """Caller-owned durable effect adapter consumed by FileService."""

    workspace_scope: str
    owner_session_id: str
    operation_id: str
    tool_call_id: str
    tool_name: str
    effect_kind: str

    @property
    def records_durable(self) -> bool:
        """Whether this sink has a durable event plane for artifact binding."""
        ...

    def prepared(
        self,
        *,
        canonical_path: Path,
        before_bytes: bytes,
        expected_after_bytes: bytes,
    ) -> bool:
        """Persist exact pre-mutation facts; False means mutation must not start."""
        ...

    def observed(
        self,
        *,
        canonical_path: Path,
        actual_after_bytes: bytes,
        expected_after_bytes: bytes,
        actual_mtime_ns: int | None,
        artifact_ref: str,
    ) -> bool:
        """Record post-mutation observation; failure must not rewrite actual bytes."""
        ...


@dataclass(frozen=True, slots=True)
class FileEffectReceipt:
    """Read-only normalized projection of one file-effect operation."""

    operation_id: str
    origin: str
    path: str
    before_sha256: str = ""
    expected_after_sha256: str = ""
    observed_after_sha256: str | None = None
    artifact_ref: str = ""
    effect_state: str = "outcome_unknown"
    receipt_state: str = "unknown"
    precondition_checked: bool | None = None
    task_applicability: str = "not_evaluated"
    causation_proven: bool = False
    current_state: str = "not_checked"
    current_sha256: str | None = None
    auto_reexecuted: bool = False
    seq: int = 0
    ts: str = ""

    def public_facts(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "origin": self.origin,
            "path": self.path,
            "before_sha256": self.before_sha256,
            "expected_after_sha256": self.expected_after_sha256,
            "observed_after_sha256": self.observed_after_sha256,
            "artifact_ref": self.artifact_ref,
            "effect_state": self.effect_state,
            "receipt_state": self.receipt_state,
            "precondition_checked": self.precondition_checked,
            "task_applicability": self.task_applicability,
            "causation_proven": self.causation_proven,
            "current_state": self.current_state,
            "current_sha256": self.current_sha256,
            "auto_reexecuted": self.auto_reexecuted,
            "seq": self.seq,
            "ts": self.ts,
        }
