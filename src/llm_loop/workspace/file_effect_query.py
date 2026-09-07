"""Read-only projection of model-tool and authenticated-human file effects."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from llm_loop.event_log.model import (
    EVENT_HUMAN_FILE_EDIT_OBSERVED,
    EVENT_HUMAN_FILE_EDIT_PREPARED,
    EVENT_HUMAN_FILE_EDIT_REJECTED,
    EVENT_TOOL_EXECUTION_EFFECT_OBSERVED,
    EVENT_TOOL_EXECUTION_EFFECT_PREPARED,
)
from llm_loop.tools.safety import link_shaped_paths
from llm_loop.workspace.file_effects import FileEffectReceipt

_OPERATION_RE = re.compile(r"^operation:([A-Za-z0-9._:-]{1,128})$")
_CURSOR_RE = re.compile(r"^before_seq:([1-9][0-9]*)$")


class FileEffectQueryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FileEffectQueryPage:
    receipts: tuple[FileEffectReceipt, ...]
    has_more: bool = False
    next_query: str = ""

    def public_facts(self) -> dict[str, object]:
        return {
            "receipts": [receipt.public_facts() for receipt in self.receipts],
            "has_more": self.has_more,
            "next_query": self.next_query,
        }


def _relative_path(payload: dict[str, Any], workspace_scope: str) -> str:
    rel = str(payload.get("relative_path") or "")
    if rel:
        return rel
    canonical = str(payload.get("canonical_path") or "")
    if not canonical:
        return ""
    try:
        return Path(canonical).resolve().relative_to(Path(workspace_scope).resolve()).as_posix()
    except (OSError, ValueError):
        return ""


def _current_prepared_state(
    *, scope: str, relative_path: str, before_sha256: str, expected_after_sha256: str
) -> tuple[str, str | None]:
    """Read current bytes for prepared-only recovery without attributing causation."""
    raw = str(relative_path or "").replace("\\", "/")
    rel = PurePosixPath(raw)
    if not raw or rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        return "current_unreadable", None
    root = Path(scope).resolve()
    target = root.joinpath(*rel.parts)
    probe = link_shaped_paths(target)
    if probe.status != "no_links":
        return "current_unreadable", None
    try:
        resolved = target.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return "current_unreadable", None
    if not resolved.exists():
        return "current_missing", None
    if not resolved.is_file():
        return "current_unreadable", None
    try:
        data = resolved.read_bytes()
    except OSError:
        return "current_unreadable", None
    digest = hashlib.sha256(data).hexdigest()
    if expected_after_sha256 and digest == expected_after_sha256:
        return "current_matches_expected", digest
    if before_sha256 and digest == before_sha256:
        return "current_matches_before", digest
    return "current_diverged", digest


class FileEffectQueryService:
    def __init__(self, event_store: Any) -> None:
        self.event_store = event_store

    def query(
        self,
        *,
        session_id: str,
        workspace_scope: str,
        query: str = "",
        limit: int = 10,
    ) -> FileEffectQueryPage:
        q = str(query or "").strip()
        exact_id = ""
        before_seq: int | None = None
        if q:
            exact = _OPERATION_RE.fullmatch(q)
            cursor = _CURSOR_RE.fullmatch(q)
            if exact:
                exact_id = exact.group(1)
            elif cursor:
                before_seq = int(cursor.group(1))
            else:
                raise FileEffectQueryError("invalid_file_effect_query")
        limit = max(1, min(int(limit), 50))
        scope = str(Path(workspace_scope).resolve())
        groups: dict[str, dict[str, Any]] = {}
        for event in self.event_store.read(session_id):
            payload = event.payload
            event_scope = str(payload.get("workspace_root") or "")
            if not event_scope:
                continue
            try:
                if str(Path(event_scope).resolve()) != scope:
                    continue
            except OSError:
                continue
            if event.type in {
                EVENT_TOOL_EXECUTION_EFFECT_PREPARED,
                EVENT_TOOL_EXECUTION_EFFECT_OBSERVED,
            }:
                op = str(payload.get("execution_id") or "")
                origin = "model_tool"
            elif event.type in {
                EVENT_HUMAN_FILE_EDIT_PREPARED,
                EVENT_HUMAN_FILE_EDIT_OBSERVED,
                EVENT_HUMAN_FILE_EDIT_REJECTED,
            }:
                op = str(payload.get("operation_id") or "")
                origin = "authenticated_user"
            else:
                continue
            if not op:
                continue
            item = groups.setdefault(op, {"operation_id": op, "origin": origin, "events": []})
            item["events"].append(event)

        receipts = [self._project(item, scope) for item in groups.values()]
        receipts.sort(key=lambda item: item.seq, reverse=True)
        if exact_id:
            receipts = [item for item in receipts if item.operation_id == exact_id]
            return FileEffectQueryPage(tuple(receipts[:1]))
        if before_seq is not None:
            receipts = [item for item in receipts if item.seq < before_seq]
        has_more = len(receipts) > limit
        selected = receipts[:limit]
        next_query = f"before_seq:{selected[-1].seq}" if has_more and selected else ""
        return FileEffectQueryPage(tuple(selected), has_more=has_more, next_query=next_query)

    @staticmethod
    def _project(item: dict[str, Any], scope: str) -> FileEffectReceipt:
        events = item["events"]
        prepared_types = {
            EVENT_TOOL_EXECUTION_EFFECT_PREPARED,
            EVENT_HUMAN_FILE_EDIT_PREPARED,
        }
        observed_types = {
            EVENT_TOOL_EXECUTION_EFFECT_OBSERVED,
            EVENT_HUMAN_FILE_EDIT_OBSERVED,
        }
        prepared = next((e for e in events if e.type in prepared_types), None)
        observed = next((e for e in reversed(events) if e.type in observed_types), None)
        rejected = next(
            (e for e in reversed(events) if e.type == EVENT_HUMAN_FILE_EDIT_REJECTED), None
        )
        primary = observed or rejected or prepared or events[-1]
        pp = prepared.payload if prepared is not None else {}
        op = str(item["operation_id"])
        origin = str(item["origin"])
        path = _relative_path((prepared or primary).payload, scope)
        before = str(pp.get("before_sha256") or "")
        expected = str(pp.get("expected_after_sha256") or "")
        actual: str | None = None
        artifact_ref = ""
        receipt_state = "unknown"
        effect_state = "outcome_unknown"
        causation = False
        current_state = "not_checked"
        current_sha256: str | None = None
        precondition: bool | None = None
        if origin == "authenticated_user" and prepared is not None:
            raw = pp.get("precondition_checked")
            precondition = bool(raw) if isinstance(raw, bool) else None
        if observed is not None:
            actual = str(observed.payload.get("actual_after_sha256") or "") or None
            artifact_ref = str(observed.payload.get("artifact_ref") or "")
            matches = observed.payload.get("matches_expected")
            effect_state = "observed_match" if matches is True else "observed_mismatch"
            receipt_state = str(observed.payload.get("receipt_state") or "recorded")
            causation = True
        elif rejected is not None:
            effect_state = "not_applied"
            receipt_state = "recorded"
        elif prepared is not None:
            current_state, current_sha256 = _current_prepared_state(
                scope=scope,
                relative_path=path,
                before_sha256=before,
                expected_after_sha256=expected,
            )
        return FileEffectReceipt(
            operation_id=op,
            origin=origin,
            path=path,
            before_sha256=before,
            expected_after_sha256=expected,
            observed_after_sha256=actual,
            artifact_ref=artifact_ref,
            effect_state=effect_state,
            receipt_state=receipt_state,
            precondition_checked=precondition,
            causation_proven=causation,
            current_state=current_state,
            current_sha256=current_sha256,
            auto_reexecuted=False,
            seq=max(e.seq for e in events),
            ts=primary.ts,
        )
