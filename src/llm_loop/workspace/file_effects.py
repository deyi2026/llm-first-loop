"""Mechanical file-effect identities and adapter contracts.

The workspace layer owns byte/path/version facts only. Event identity stays with the
caller: model-tool operations adapt ToolExecutionJournal; a future authenticated human
entry adapts EventStore. Nothing here creates model, user, task, or completion authority.
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
