"""Compact read-only restart-continuity projection for repeated Web polling."""
from __future__ import annotations

from typing import Any

from llm_loop.core.interruption_resume import open_execution_facts, select_open_checkpoint_events

# Cache only the existing bounded mechanical identity/state schema, never
# newly introduced payload fields from the execution projector.
_MECHANICAL_FIELDS = {
    "tool_executions": ("execution_id", "round", "tool_call_id", "tool_name", "state", "auto_reexecuted"),
    "external_executions": ("job_id", "executor", "state", "cancel_requested", "auto_reclaim"),
}


def _mechanical_projection(facts: dict[str, Any]) -> dict[str, Any]:
    return {
        key: [
            {field: row[field] for field in fields
             if field in row and type(row[field]) in (str, int, bool)}
            for row in rows[-8:] if isinstance(row, dict)
        ]
        for key, fields in _MECHANICAL_FIELDS.items()
        if isinstance(rows := facts.get(key), list) and rows
    }


def continuity_facts(estore: Any, session_id: str) -> dict[str, Any]:
    events = getattr(estore, "read_cached", estore.read)(session_id) or []
    last_run_end = next(
        (pos for pos in range(len(events) - 1, -1, -1)
         if str(getattr(events[pos], "type", "")) == "run.end"),
        -1,
    )
    open_events = events[last_run_end + 1 :]
    has_open_run_fact = any(
        str(getattr(event, "type", "")) == "request.meta"
        or str(getattr(event, "type", "")) == "llm.partial_checkpoint"
        or str(getattr(event, "type", "")).startswith("tool.execution.")
        or str(getattr(event, "type", "")).startswith("external.execution.")
        for event in open_events
    )
    if not has_open_run_fact:
        return {"available": True, "open": False}
    model_checkpoint, latest_checkpoint = select_open_checkpoint_events(open_events)
    mechanical = _mechanical_projection(open_execution_facts(events, after_pos=last_run_end))
    chosen = model_checkpoint or latest_checkpoint
    payload = dict(getattr(chosen, "payload", None) or {}) if chosen is not None else {}
    return {
        "available": True,
        "open": bool(chosen is not None or mechanical),
        "source": (
            "open_stream_checkpoint" if chosen is not None else "open_execution_state"
        ),
        "provider": str(payload.get("provider") or ""),
        "model": str(payload.get("model") or ""),
        "text_chars": int(payload.get("text_chars") or 0),
        "reasoning_chars": int(payload.get("reasoning_chars") or 0),
        "checkpoint_seq": int(getattr(chosen, "seq", 0) or 0) if chosen is not None else 0,
        "mechanical_execution": mechanical,
    }
