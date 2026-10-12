"""Method-card injection helpers (EVO-20260923-618f7fd1).

One program-origin surface, fail-open: a single per-run status-layer reminder
fired at the no-tool-call final boundary when exact method hydrations lack any
method_manage record_use.

The original session-opening ACTIVE-card list appendix (surface 1) was retired
2026-09-24: measured interference on weak local models (identity turns answered
from training prior instead of evidence; session 6aec21cb vs control f66027f9)
plus L2-2 "retrievable != injectable". Method visibility stays behind the
search_records(kind=method) schema entry.

Everything here is mechanical: no policy retries, no fuzzy matching.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm_loop.core.injection_labels import (
    InjectionLayer,
    origin_metadata,
    render_program_appendix,
)
from llm_loop.core.message import Message, MessageSource

_REMINDER_KIND = "method_use_reminder"


@dataclass(frozen=True)
class MethodUseLedger:
    """Method refs exactly hydrated vs. refs with a record_use this run."""

    hydrated: tuple[str, ...]
    recorded: tuple[str, ...]

    def unrecorded(self) -> tuple[str, ...]:
        seen: list[str] = []
        for ref in self.hydrated:
            if ref not in self.recorded and ref not in seen:
                seen.append(ref)
        return tuple(seen)


def scan_method_use_ledger(tool_trace: list[Any]) -> MethodUseLedger:
    """Derive hydrated vs. recorded method refs from this run's tool trace."""
    hydrated: list[str] = []
    recorded: list[str] = []
    for row in tool_trace or []:
        try:
            if isinstance(row, dict):
                name = str(row.get("name", "") or "")
                arguments = row.get("arguments") or {}
                status = str(row.get("status", "success") or "")
            else:
                name = str(getattr(row, "name", "") or "")
                arguments = getattr(row, "arguments", None) or {}
                status = str(getattr(row, "status", "success") or "")
            if status != "success":
                continue
            if name == "search_records":
                if str(arguments.get("kind", "")) != "method":
                    continue
                query = str(arguments.get("query", "") or "").strip()
                if query.startswith("method:"):
                    hydrated.append(query)
            elif name == "method_manage":
                if str(arguments.get("action", "")) != "record_use":
                    continue
                ref = str(arguments.get("method_ref", "") or "").strip()
                if ref:
                    recorded.append(ref)
        except Exception:
            continue
    return MethodUseLedger(hydrated=tuple(hydrated), recorded=tuple(recorded))


def build_use_reminder_message(unrecorded_refs: tuple[str, ...]) -> Message:
    """Status-layer reminder carrier; caller fires it once per run."""
    refs = ", ".join(unrecorded_refs[:6]) + (
        f" 等{len(unrecorded_refs)}张" if len(unrecorded_refs) > 6 else ""
    )
    body = (
        f"方法 use 回记提醒（每 run 至多一次，不阻塞收尾）：本 run 已精确水合方法卡 "
        f"{refs}，尚无对应 method_manage(action=record_use) 回记；"
        "适用则补 applied/adapted/not_applicable/rejected，"
        "或再次直接给出最终答复。"
    )
    content = render_program_appendix(
        body,
        InjectionLayer.STATUS,
        slot_kind="method_use_reminder",
    )
    return Message(
        role="user",
        source=MessageSource.USER,
        content=content,
        metadata=origin_metadata(
            InjectionLayer.STATUS,
            injection_kind=_REMINDER_KIND,
        ),
    )
