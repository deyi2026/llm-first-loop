"""Durable mechanical SubAgent delivery/result facts.

This layer stores transport facts only.  It does not recover workers, decide whether a
result is relevant, force a parent to read a terminal child, or authorize reclaim.
EventStore is the append-only source of truth; generation is a fencing key inherited
from ``SubAgentTopologyJournal``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from llm_loop.event_log.model import (
    EVENT_SUBAGENT_CANCEL_REQUESTED,
    EVENT_SUBAGENT_MAILBOX_QUEUED,
    EVENT_SUBAGENT_REPORT_QUEUED,
    EVENT_SUBAGENT_RESULT_AVAILABLE,
)


@dataclass(frozen=True)
class MailboxRecord:
    message_id: str
    child_id: str
    parent_id: str
    generation: str
    sender_id: str
    content: str
    seq: int = 0
    durable: bool = True


@dataclass(frozen=True)
class ReportRecord:
    report_id: str
    child_id: str
    parent_id: str
    generation: str
    content: str
    seq: int = 0
    durable: bool = True


@dataclass(frozen=True)
class ResultRecord:
    result_id: str
    child_id: str
    parent_id: str
    generation: str
    payload: dict[str, Any]
    report_ids: tuple[str, ...] = ()
    seq: int = 0
    durable: bool = True


@dataclass(frozen=True)
class CancelRecord:
    cancel_id: str
    child_id: str
    parent_id: str
    generation: str
    reason: str
    seq: int = 0
    durable: bool = True


class SubAgentDeliveryJournal:
    """Append/read generation-scoped SubAgent transport facts without semantics."""

    def __init__(self, event_store: Any | None) -> None:
        self.event_store = event_store

    @property
    def enabled(self) -> bool:
        store = self.event_store
        return store is not None and bool(getattr(store, "enabled", False))

    def _append(self, child_id: str, event_type: str, payload: dict[str, object]) -> Any | None:
        store = self.event_store
        if not self.enabled:
            return False  # explicit legacy/no-WAL marker; caller may keep process-local behavior
        assert store is not None
        return store.append(child_id, event_type, payload)

    def _read(self, child_id: str) -> list[Any]:
        store = self.event_store
        if not self.enabled or store is None or not store.exists(child_id):
            return []
        return list(store.read(child_id) or [])

    @staticmethod
    def _mailbox_from_event(event: Any) -> MailboxRecord | None:
        if str(getattr(event, "type", "")) != EVENT_SUBAGENT_MAILBOX_QUEUED:
            return None
        p = dict(getattr(event, "payload", None) or {})
        message_id = str(p.get("message_id") or "")
        child_id = str(p.get("child_id") or "")
        parent_id = str(p.get("parent_id") or "")
        generation = str(p.get("generation") or "")
        sender_id = str(p.get("sender_id") or "")
        if not all((message_id, child_id, parent_id, generation, sender_id)):
            return None
        return MailboxRecord(
            message_id=message_id,
            child_id=child_id,
            parent_id=parent_id,
            generation=generation,
            sender_id=sender_id,
            content=str(p.get("content") or ""),
            seq=int(getattr(event, "seq", 0) or 0),
        )

    @staticmethod
    def _report_from_event(event: Any) -> ReportRecord | None:
        if str(getattr(event, "type", "")) != EVENT_SUBAGENT_REPORT_QUEUED:
            return None
        p = dict(getattr(event, "payload", None) or {})
        report_id = str(p.get("report_id") or "")
        child_id = str(p.get("child_id") or "")
        parent_id = str(p.get("parent_id") or "")
        generation = str(p.get("generation") or "")
        if not all((report_id, child_id, parent_id, generation)):
            return None
        return ReportRecord(
            report_id=report_id,
            child_id=child_id,
            parent_id=parent_id,
            generation=generation,
            content=str(p.get("content") or ""),
            seq=int(getattr(event, "seq", 0) or 0),
        )

    @staticmethod
    def _result_from_event(event: Any) -> ResultRecord | None:
        if str(getattr(event, "type", "")) != EVENT_SUBAGENT_RESULT_AVAILABLE:
            return None
        p = dict(getattr(event, "payload", None) or {})
        result_id = str(p.get("result_id") or "")
        child_id = str(p.get("child_id") or "")
        parent_id = str(p.get("parent_id") or "")
        generation = str(p.get("generation") or "")
        raw_result = p.get("result")
        if not all((result_id, child_id, parent_id, generation)) or not isinstance(raw_result, dict):
            return None
        report_ids = p.get("report_ids")
        return ResultRecord(
            result_id=result_id,
            child_id=child_id,
            parent_id=parent_id,
            generation=generation,
            payload=dict(raw_result),
            report_ids=tuple(str(x) for x in report_ids if str(x))
            if isinstance(report_ids, list)
            else (),
            seq=int(getattr(event, "seq", 0) or 0),
        )

    @staticmethod
    def _cancel_from_event(event: Any) -> CancelRecord | None:
        if str(getattr(event, "type", "")) != EVENT_SUBAGENT_CANCEL_REQUESTED:
            return None
        p = dict(getattr(event, "payload", None) or {})
        cancel_id = str(p.get("cancel_id") or "")
        child_id = str(p.get("child_id") or "")
        parent_id = str(p.get("parent_id") or "")
        generation = str(p.get("generation") or "")
        if not all((cancel_id, child_id, parent_id, generation)):
            return None
        return CancelRecord(
            cancel_id=cancel_id,
            child_id=child_id,
            parent_id=parent_id,
            generation=generation,
            reason=str(p.get("reason") or "parent_lifecycle_cancel"),
            seq=int(getattr(event, "seq", 0) or 0),
        )

    def settlement_committed(
        self,
        *,
        child_id: str,
        parent_id: str,
        generation: str,
        result_id: str,
    ) -> bool:
        """Derive settlement from a parent tool receipt followed by WAL commit."""
        store = self.event_store
        if not self.enabled or store is None or not store.exists(parent_id):
            return False
        message_seq_by_call: dict[str, int] = {}
        commit_seq_by_call: dict[str, int] = {}
        for event in store.read(parent_id) or []:
            event_type = str(getattr(event, "type", "") or "")
            payload = dict(getattr(event, "payload", None) or {})
            tool_call_id = str(payload.get("tool_call_id") or "")
            if not tool_call_id:
                continue
            seq = int(getattr(event, "seq", 0) or 0)
            if event_type == "message.appended" and str(payload.get("tool_name") or "") == "subagent_result":
                metadata = payload.get("metadata")
                binding = metadata.get("subagent_settlement") if isinstance(metadata, dict) else None
                if not isinstance(binding, dict):
                    continue
                if (
                    str(binding.get("child_id") or "") == child_id
                    and str(binding.get("parent_id") or "") == parent_id
                    and str(binding.get("generation") or "") == generation
                    and str(binding.get("result_id") or "") == result_id
                ):
                    message_seq_by_call[tool_call_id] = seq
            elif (
                event_type == "tool.execution.receipt_committed"
                and str(payload.get("tool_name") or "") == "subagent_result"
            ):
                commit_seq_by_call[tool_call_id] = seq
        return any(
            commit_seq_by_call.get(call_id, 0) > message_seq
            for call_id, message_seq in message_seq_by_call.items()
        )

    def queue_mailbox(
        self,
        *,
        child_id: str,
        parent_id: str,
        generation: str,
        sender_id: str,
        content: str,
    ) -> MailboxRecord | None:
        message_id = uuid.uuid4().hex
        if not self.enabled:
            return MailboxRecord(
                message_id=message_id,
                child_id=child_id,
                parent_id=parent_id,
                generation=generation,
                sender_id=sender_id,
                content=content,
                durable=False,
            )
        event = self._append(
            child_id,
            EVENT_SUBAGENT_MAILBOX_QUEUED,
            {
                "message_id": message_id,
                "child_id": child_id,
                "parent_id": parent_id,
                "generation": generation,
                "sender_id": sender_id,
                "content": content,
            },
        )
        if not event:
            return None
        return MailboxRecord(
            message_id=message_id,
            child_id=child_id,
            parent_id=parent_id,
            generation=generation,
            sender_id=sender_id,
            content=content,
            seq=int(getattr(event, "seq", 0) or 0),
        )

    def queue_report(
        self,
        *,
        child_id: str,
        parent_id: str,
        generation: str,
        content: str,
    ) -> ReportRecord | None:
        report_id = uuid.uuid4().hex
        if not self.enabled:
            return ReportRecord(
                report_id=report_id,
                child_id=child_id,
                parent_id=parent_id,
                generation=generation,
                content=content,
                durable=False,
            )
        event = self._append(
            child_id,
            EVENT_SUBAGENT_REPORT_QUEUED,
            {
                "report_id": report_id,
                "child_id": child_id,
                "parent_id": parent_id,
                "generation": generation,
                "content": content,
            },
        )
        if not event:
            return None
        return ReportRecord(
            report_id=report_id,
            child_id=child_id,
            parent_id=parent_id,
            generation=generation,
            content=content,
            seq=int(getattr(event, "seq", 0) or 0),
        )

    def result_available(
        self,
        *,
        child_id: str,
        parent_id: str,
        generation: str,
        result: dict[str, Any],
        report_ids: list[str] | tuple[str, ...] = (),
    ) -> ResultRecord | None:
        existing = self.result(child_id, generation)
        normalized_report_ids = tuple(str(x) for x in report_ids if str(x))
        if existing is not None:
            if existing.parent_id == parent_id and existing.payload == result and existing.report_ids == normalized_report_ids:
                return existing
            return None
        result_id = f"result-{generation}"
        if not self.enabled:
            return ResultRecord(
                result_id=result_id,
                child_id=child_id,
                parent_id=parent_id,
                generation=generation,
                payload=dict(result),
                report_ids=normalized_report_ids,
                durable=False,
            )
        event = self._append(
            child_id,
            EVENT_SUBAGENT_RESULT_AVAILABLE,
            {
                "result_id": result_id,
                "child_id": child_id,
                "parent_id": parent_id,
                "generation": generation,
                "result": dict(result),
                "report_ids": list(normalized_report_ids),
            },
        )
        if not event:
            return None
        return ResultRecord(
            result_id=result_id,
            child_id=child_id,
            parent_id=parent_id,
            generation=generation,
            payload=dict(result),
            report_ids=normalized_report_ids,
            seq=int(getattr(event, "seq", 0) or 0),
        )

    def cancel_requested(
        self,
        *,
        child_id: str,
        parent_id: str,
        generation: str,
        reason: str,
    ) -> CancelRecord | None:
        existing = self.cancel_state(child_id, generation)
        if existing is not None:
            if existing.parent_id == parent_id:
                return existing
            return None
        cancel_id = f"cancel-{generation}"
        if not self.enabled:
            return CancelRecord(
                cancel_id=cancel_id,
                child_id=child_id,
                parent_id=parent_id,
                generation=generation,
                reason=reason,
                durable=False,
            )
        event = self._append(
            child_id,
            EVENT_SUBAGENT_CANCEL_REQUESTED,
            {
                "cancel_id": cancel_id,
                "child_id": child_id,
                "parent_id": parent_id,
                "generation": generation,
                "reason": str(reason or "parent_lifecycle_cancel"),
            },
        )
        if not event:
            return None
        return CancelRecord(
            cancel_id=cancel_id,
            child_id=child_id,
            parent_id=parent_id,
            generation=generation,
            reason=str(reason or "parent_lifecycle_cancel"),
            seq=int(getattr(event, "seq", 0) or 0),
        )

    def pending_mailbox(
        self, child_id: str, generation: str, *, delivered_ids: set[str]
    ) -> list[MailboxRecord]:
        rows = [
            row
            for event in self._read(child_id)
            if (row := self._mailbox_from_event(event)) is not None
            and row.generation == generation
            and row.message_id not in delivered_ids
        ]
        return sorted(rows, key=lambda row: (row.seq, row.message_id))

    def reports(self, child_id: str, generation: str) -> list[ReportRecord]:
        rows = [
            row
            for event in self._read(child_id)
            if (row := self._report_from_event(event)) is not None and row.generation == generation
        ]
        return sorted(rows, key=lambda row: (row.seq, row.report_id))

    def result(self, child_id: str, generation: str) -> ResultRecord | None:
        rows = [
            row
            for event in self._read(child_id)
            if (row := self._result_from_event(event)) is not None and row.generation == generation
        ]
        return max(rows, key=lambda row: row.seq) if rows else None

    def cancel_state(self, child_id: str, generation: str) -> CancelRecord | None:
        rows = [
            row
            for event in self._read(child_id)
            if (row := self._cancel_from_event(event)) is not None and row.generation == generation
        ]
        return max(rows, key=lambda row: row.seq) if rows else None
