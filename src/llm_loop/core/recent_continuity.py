"""Prompt-tail continuity for the recent human/model working dialogue.

This module is deliberately structural. It never classifies whether user text looks
like an answer, continuation, reference, or new task. On an initial genuine-human
round it restores only the immediately preceding completed model answer, then
guarantees that this adjacent model state and the current human ingress form the final
prompt suffix. Historical human instructions remain retired/indexed and are never
automatically re-promoted as fresh role=user authority.
"""

from __future__ import annotations

import json
from typing import Any

from llm_loop.core.episode_history import is_human_user_message
from llm_loop.core.prompt_eligibility import LEGACY_PROGRAM_FINAL_MARKER
from llm_loop.feedback.honesty import PROGRAM_FEEDBACK_PREFIXES


def _metadata(message: Any) -> dict[str, Any]:
    value = getattr(message, "metadata", None)
    return value if isinstance(value, dict) else {}


RECENT_ASSISTANT_CHAR_LIMIT = 32_768


def _is_completed_model_answer(message: Any) -> bool:
    md = _metadata(message)
    content = str(getattr(message, "content", "") or "")
    return bool(
        getattr(message, "role", "") == "assistant"
        and md.get("answer_origin") == "model"
        and md.get("run_end_reason") == "completed"
        and md.get("episode_resolution_candidate") is True
        and md.get("program_origin") is not True
        and md.get("llm_interrupted") is not True
        and not getattr(message, "tool_calls", None)
        and content
        and content.strip() != LEGACY_PROGRAM_FINAL_MARKER
        and not content.startswith(PROGRAM_FEEDBACK_PREFIXES)
    )


def latest_model_assistant_before_turn(
    session_messages: list[Any], current_turn_ref: int | None
) -> Any | None:
    """Return the nearest real final model assistant in the immediately prior turn."""
    if (
        current_turn_ref is None
        or current_turn_ref <= 0
        or current_turn_ref >= len(session_messages)
    ):
        return None
    current = session_messages[current_turn_ref]
    if not is_human_user_message(current):
        return None
    for idx in range(current_turn_ref - 1, -1, -1):
        message = session_messages[idx]
        if is_human_user_message(message):
            break
        md = _metadata(message)
        content = str(getattr(message, "content", "") or "")
        if (
            getattr(message, "role", "") == "assistant"
            and md.get("answer_origin") == "model"
            and md.get("program_origin") is not True
            and md.get("llm_interrupted") is not True
            and not getattr(message, "tool_calls", None)
            and content
            and content.strip() != LEGACY_PROGRAM_FINAL_MARKER
            and not content.startswith(PROGRAM_FEEDBACK_PREFIXES)
        ):
            return message
    return None


def _recent_assistant_wire(message: Any | None) -> dict[str, Any] | None:
    """Project only adjacent completed assistant text for short-turn continuity.

    Historical human instructions are intentionally excluded: once an episode is
    resolved they remain durable/retrievable but must not regain role=user authority
    merely because a later human ingress arrives. Hidden reasoning/provider replay is
    also excluded here; model-specific replay policy owns that transport concern.
    """
    if message is None:
        return None
    content = str(getattr(message, "content", "") or "")
    if not content:
        return None
    if len(content) > RECENT_ASSISTANT_CHAR_LIMIT:
        content = content[-RECENT_ASSISTANT_CHAR_LIMIT:]
    return {"role": "assistant", "content": content}


def _resume_message(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(state, dict):
        return None
    text_tail = str(state.get("text_tail") or "")
    reasoning_tail = str(state.get("reasoning_tail") or "")
    replay = state.get("provider_replay")
    if not text_tail and not reasoning_tail and not isinstance(replay, dict):
        return None
    out: dict[str, Any] = {"role": "assistant", "content": text_tail}
    if reasoning_tail:
        out["reasoning_content"] = reasoning_tail
    # Opaque provider-native replay is transport state, not prose. Keep the
    # internal marker so LLMClient can project it only to its originating provider;
    # foreign providers deterministically strip it. Partial tool-call drafts remain
    # non-executable and are intentionally not projected here.
    if isinstance(replay, dict):
        out["_provider_replay"] = replay
    return out


def _current_user_wire_index(built: list[dict], current: Any) -> int | None:
    """Locate the current genuine-human wire without equating raw and wire text.

    ``Message.to_llm_dict`` may mechanically append attachment facts. History may
    additionally append a current-turn capability-boundary fact block. Both are
    provider-view representations of the same durable human message, so match the
    exact projected user text plus only that known factual suffix. Search from the
    tail to avoid an older identical human message.
    """
    projected = current.to_llm_dict() if hasattr(current, "to_llm_dict") else None
    projected_text = (
        str(projected.get("content") or "")
        if isinstance(projected, dict)
        else str(getattr(current, "content", "") or "")
    )
    capability_suffix = "\n[能力边界事实]"
    for idx in range(len(built) - 1, -1, -1):
        item = built[idx]
        if item.get("role") != "user":
            continue
        wire_text = str(item.get("content") or "")
        if wire_text == projected_text or wire_text.startswith(projected_text + capability_suffix):
            return idx
    return None


def _resume_runtime_fact(state: dict[str, Any] | None) -> str:
    """Return provider-only mechanical continuity facts for one interrupted run.

    Model-origin partial bytes remain an assistant message.  This marker carries only
    runtime facts that cannot be expressed by that text/reasoning alone: provider
    truncation, sparse-checkpoint selection, and durable execution lifecycle.  It
    never says what task is active or which action should happen next.
    """
    if not isinstance(state, dict):
        return ""
    payload: dict[str, Any] = {}
    if state.get("provider_truncated") is True:
        payload.update(
            {
                "previous_assistant_output_truncated": True,
                "previous_assistant_output_complete": False,
                "partial_output_persisted": True,
                "finish_reason": str(state.get("finish_reason") or "")[:80],
            }
        )
    mechanical = state.get("mechanical_execution")
    if isinstance(mechanical, dict) and mechanical:
        payload["interrupted_execution_state"] = mechanical
    if state.get("sparse_latest_skipped") is True:
        payload["checkpoint_selection"] = {
            "latest_checkpoint_seq": int(state.get("latest_checkpoint_seq") or 0),
            "model_state_checkpoint_seq": int(state.get("checkpoint_seq") or 0),
            "latest_checkpoint_model_chars": int(state.get("latest_checkpoint_model_chars") or 0),
        }
    if not payload:
        return ""
    return "[runtime_continuity] " + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def apply_recent_continuity_suffix(
    built: list[dict],
    *,
    session_messages: list[Any],
    current_turn_ref: int | None,
    interruption_resume: dict[str, Any] | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """Make recent assistant/current human the final provider-visible suffix.

    Returns a fresh list only when an initial genuine-human ingress is present.
    ``interruption_resume`` wins over the prior completed assistant because it is the
    more recent unfinished model state. For provider token-limit truncation only, a
    provider-only structured runtime fact is attached to the provider view of the
    current genuine-human wire message, after the exact human text and under an
    explicit runtime marker. Durable Session content remains byte-exact human input.
    This keeps the stable system prefix unchanged and avoids providers that reject a
    second/mid-turn system role. The fact contains no continuation directive.
    """
    if (
        current_turn_ref is None
        or current_turn_ref < 0
        or current_turn_ref >= len(session_messages)
    ):
        return built, {"applied": False, "reason": "no_current_turn"}
    current = session_messages[current_turn_ref]
    if not is_human_user_message(current):
        return built, {"applied": False, "reason": "not_human_ingress"}
    turn_advanced = any(
        getattr(message, "role", "") in {"assistant", "tool"}
        for message in session_messages[current_turn_ref + 1 :]
    )
    user_idx = _current_user_wire_index(built, current)
    if user_idx is None:
        return built, {"applied": False, "reason": "current_user_not_in_wire"}

    source = "current_user_only"
    assistant_wire = _resume_message(interruption_resume)
    runtime_fact = _resume_runtime_fact(interruption_resume)
    adjacent_assistant = latest_model_assistant_before_turn(session_messages, current_turn_ref)
    recent_assistant_wire = _recent_assistant_wire(adjacent_assistant)

    # Once a turn advances, native assistant(tool_calls)->tool order is authoritative.
    # Do not re-append the current user or any interruption partial at the tail.  But if
    # the initial request used the immediately prior completed assistant as adjacency
    # context, keep that same visible assistant immediately before the current human on
    # every provider round in this run.  Otherwise round 1 has
    #   system -> prior-assistant -> current-user
    # while round 2 drops prior-assistant and destroys exact token-prefix reuse.
    # This is representation stability only: no historical user, reasoning, tool span,
    # or completion judgement is restored.
    if turn_advanced:
        if recent_assistant_wire is None:
            return built, {"applied": False, "reason": "turn_already_advanced"}
        out = list(built)
        # Remove one identical provider-visible copy if another projection retained it,
        # then place it at the same adjacency boundary used by the initial round.
        for idx in range(user_idx - 1, -1, -1):
            item = out[idx]
            if (
                item.get("role") == "assistant"
                and str(item.get("content") or "") == recent_assistant_wire["content"]
                and not item.get("tool_calls")
            ):
                out.pop(idx)
                user_idx -= 1
                break
        out.insert(user_idx, dict(recent_assistant_wire))
        return out, {
            "applied": True,
            "source": "recent_assistant_sticky",
            "moved_after_user": 0,
            "rehydrated": True,
            "runtime_fact": False,
            "dialogue_pairs": 0,
            "assistant_context": 1,
            "historical_user_messages": 0,
        }
    if assistant_wire is not None or runtime_fact:
        assert interruption_resume is not None
        source = str(interruption_resume.get("source") or "interruption_resume")
    elif recent_assistant_wire is not None:
        source = "recent_assistant_only"

    before = list(built[:user_idx])
    after_user = list(built[user_idx + 1 :])
    current_wire = dict(built[user_idx])

    # If the adjacent assistant survived another projection, remove that exact visible
    # content before re-appending it at the suffix. Historical human messages are never
    # rehydrated here.
    if recent_assistant_wire is not None:
        for idx in range(len(before) - 1, -1, -1):
            item = before[idx]
            if (
                item.get("role") == "assistant"
                and str(item.get("content") or "") == recent_assistant_wire["content"]
                and not item.get("tool_calls")
            ):
                before.pop(idx)
                break

    # Any build-time dynamic/program material that appeared after current human is
    # moved ahead of recent assistant context. Exact current human ingress remains final.
    out = before + after_user
    if recent_assistant_wire is not None and assistant_wire is None:
        out.append(dict(recent_assistant_wire))
    if runtime_fact:
        # Preserve the exact already-projected current-human wire (attachments and
        # current-turn factual capability boundary included); only append ephemeral
        # provider runtime provenance. Durable Message.content remains untouched.
        projected_current_text = str(current_wire.get("content") or "")
        current_wire["content"] = (
            f"{projected_current_text}\n\n[provider_runtime_fact—not_human_text]\n{runtime_fact}"
        )
    if assistant_wire is not None:
        # Exact unfinished model state is newer than the last completed dialogue pair.
        out.append(assistant_wire)
    out.append(current_wire)
    return out, {
        "applied": True,
        "source": source,
        "moved_after_user": len(after_user),
        "rehydrated": bool(recent_assistant_wire or assistant_wire is not None),
        "runtime_fact": bool(runtime_fact),
        "dialogue_pairs": 0,
        "assistant_context": int(recent_assistant_wire is not None and assistant_wire is None),
        "historical_user_messages": 0,
    }
