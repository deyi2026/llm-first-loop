"""Pure restart-continuity selection over durable event facts.

This module never interprets task meaning, relevance, completion value, or next action.
It selects structural model-output checkpoints and projects mechanical execution
lifecycle facts for the model to reason over after a process interruption.
"""

from __future__ import annotations

from typing import Any


def _checkpoint_has_model_bytes(event: Any) -> bool:
    """Whether a checkpoint contains model-origin text/reasoning worth restoring.

    Provider-native replay/tool drafts are durable transport facts, but a checkpoint
    containing only those facts must not displace an earlier non-empty model working
    state after a restart.
    """
    payload = dict(getattr(event, "payload", None) or {})
    if str(payload.get("text_tail") or "") or str(payload.get("reasoning_tail") or ""):
        return True
    return bool(int(payload.get("text_chars") or 0) or int(payload.get("reasoning_chars") or 0))


def _completed_model_answer_after(open_events: list[Any], checkpoint_pos: int) -> bool:
    """Return True only for a durable terminal model answer after a checkpoint."""
    for later in open_events[checkpoint_pos + 1 :]:
        if str(getattr(later, "type", "")) != "message.appended":
            continue
        payload = dict(getattr(later, "payload", None) or {})
        md = dict(payload.get("metadata") or {})
        if (
            payload.get("role") == "assistant"
            and md.get("answer_origin") == "model"
            and md.get("llm_interrupted") is not True
            and md.get("run_end_reason") == "completed"
            and not payload.get("tool_calls")
        ):
            return True
    return False


def select_open_checkpoint_events(open_events: list[Any]) -> tuple[Any | None, Any | None]:
    """Return (latest useful model checkpoint, latest checkpoint of any kind)."""
    checkpoints = [
        (pos, event)
        for pos, event in enumerate(open_events)
        if str(getattr(event, "type", "")) == "llm.partial_checkpoint"
    ]
    if not checkpoints:
        return None, None
    latest_pos, latest = checkpoints[-1]
    # A durable terminal model answer after the newest checkpoint settles the open
    # model state even if process death happened before the run.end append.
    if _completed_model_answer_after(open_events, latest_pos):
        return None, None
    for pos, event in reversed(checkpoints):
        if not _checkpoint_has_model_bytes(event):
            continue
        if _completed_model_answer_after(open_events, pos):
            return None, latest
        return event, latest
    return None, latest


def open_execution_facts(events: list[Any], *, after_pos: int) -> dict[str, Any]:
    """Project durable execution lifecycle only; never infer task meaning or re-execute.

    Tool attempts are limited to the crash-open run. External jobs are session-scoped
    durable resources and therefore remain relevant across run boundaries until a
    terminal event arrives. Returned fields are mechanical identities/states only.
    """
    open_events = events[after_pos + 1 :]
    tool_states: dict[str, dict[str, Any]] = {}
    for event in open_events:
        etype = str(getattr(event, "type", ""))
        if not etype.startswith("tool.execution."):
            continue
        payload = dict(getattr(event, "payload", None) or {})
        execution_id = str(payload.get("execution_id") or "")
        if not execution_id:
            continue
        state = tool_states.setdefault(
            execution_id,
            {
                "execution_id": execution_id,
                "round": int(payload.get("round") or 0),
                "tool_call_id": str(payload.get("tool_call_id") or ""),
                "tool_name": str(payload.get("tool_name") or ""),
                "declared_seq": 0,
                "started_seq": 0,
                "finished_seq": 0,
                "committed_seq": 0,
                "recovered": False,
            },
        )
        seq = int(getattr(event, "seq", 0) or 0)
        if etype == "tool.execution.declared":
            state["declared_seq"] = seq
        elif etype == "tool.execution.started":
            state["started_seq"] = seq
        elif etype == "tool.execution.finished":
            state["finished_seq"] = seq
        elif etype == "tool.execution.receipt_committed":
            state["committed_seq"] = seq
            state["recovered"] = bool(payload.get("recovered"))

    tool_facts: list[dict[str, Any]] = []
    for state in tool_states.values():
        committed = int(state.get("committed_seq") or 0)
        # Once a receipt is committed (including restart recovery), the ordinary tool
        # message is already the provider-visible mechanical truth. Do not duplicate
        # it into the current human wire as a runtime fact.
        if committed:
            continue
        if int(state.get("finished_seq") or 0):
            lifecycle_state = "finished_receipt_uncommitted"
        elif int(state.get("started_seq") or 0):
            lifecycle_state = "started_outcome_unknown"
        else:
            lifecycle_state = "declared_not_started"
        tool_facts.append(
            {
                "execution_id": state["execution_id"],
                "round": state["round"],
                "tool_call_id": state["tool_call_id"],
                "tool_name": state["tool_name"],
                "state": lifecycle_state,
                "auto_reexecuted": False,
            }
        )
    tool_facts = tool_facts[-8:]

    external: dict[str, dict[str, Any]] = {}
    for event in events:
        etype = str(getattr(event, "type", ""))
        if not etype.startswith("external.execution."):
            continue
        payload = dict(getattr(event, "payload", None) or {})
        job_id = str(payload.get("job_id") or "")
        if not job_id:
            continue
        state = external.setdefault(
            job_id,
            {
                "job_id": job_id,
                "executor": "",
                "launch_seq": 0,
                "terminal_seq": 0,
                "cancel_requested": False,
            },
        )
        seq = int(getattr(event, "seq", 0) or 0)
        if etype == "external.execution.launched":
            state["executor"] = str(payload.get("executor") or "")
            state["launch_seq"] = seq
        elif etype == "external.execution.cancel_requested":
            state["cancel_requested"] = True
        elif etype == "external.execution.terminal":
            state["terminal_seq"] = seq

    external_facts = [
        {
            "job_id": state["job_id"],
            "executor": state["executor"],
            "state": "launched_without_terminal",
            "cancel_requested": bool(state["cancel_requested"]),
            "auto_reclaim": False,
        }
        for state in external.values()
        if int(state.get("launch_seq") or 0) and not int(state.get("terminal_seq") or 0)
    ][-8:]

    out: dict[str, Any] = {}
    if tool_facts:
        out["tool_executions"] = tool_facts
    if external_facts:
        out["external_executions"] = external_facts
    return out


__all__ = ["open_execution_facts", "select_open_checkpoint_events"]
