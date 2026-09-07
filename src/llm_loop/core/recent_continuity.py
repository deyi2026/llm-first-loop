"""Prompt-tail continuity for the recent human/model working dialogue.

This module is deliberately structural. It never classifies whether user text looks
like an answer, continuation, reference, or new task. On an initial genuine-human
round it restores a bounded exact window of the most recent completed human→model
dialogue pairs, then guarantees that the latest model state and current human ingress
form the final prompt suffix. Older resolved material remains indexed/retrievable.
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


RECENT_DIALOGUE_PAIR_LIMIT = 3
RECENT_DIALOGUE_CHAR_LIMIT = 32_768


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


def recent_completed_dialogue_pairs(
    session_messages: list[Any], current_turn_ref: int | None
) -> list[tuple[Any, Any]]:
    """Return up to three exact recent human/final-model pairs under a char cap.

    Selection is purely chronological/mechanical. Tool protocol, program output,
    interrupted answers, and unresolved turns are not promoted into dialogue state.
    """
    if current_turn_ref is None or current_turn_ref <= 0:
        return []
    pairs_rev: list[tuple[Any, Any]] = []
    total_chars = 0
    end = min(int(current_turn_ref), len(session_messages))
    human_indices = [
        idx for idx in range(end) if is_human_user_message(session_messages[idx])
    ]
    for pos in range(len(human_indices) - 1, -1, -1):
        start = human_indices[pos]
        span_end = human_indices[pos + 1] if pos + 1 < len(human_indices) else end
        final = next(
            (
                session_messages[idx]
                for idx in range(span_end - 1, start, -1)
                if _is_completed_model_answer(session_messages[idx])
            ),
            None,
        )
        if final is None:
            # An unresolved/interrupted human turn is a hard structural boundary.
            # Never skip across it to resurrect an older completed task.
            break
        user = session_messages[start]
        pair_chars = len(str(getattr(user, "content", "") or "")) + len(
            str(getattr(final, "content", "") or "")
        )
        if pairs_rev and total_chars + pair_chars > RECENT_DIALOGUE_CHAR_LIMIT:
            break
        pairs_rev.append((user, final))
        total_chars += pair_chars
        if len(pairs_rev) >= RECENT_DIALOGUE_PAIR_LIMIT:
            break
    pairs_rev.reverse()
    return pairs_rev


def latest_model_assistant_before_turn(
    session_messages: list[Any], current_turn_ref: int | None
) -> Any | None:
    """Return the nearest real final model assistant in the immediately prior turn."""
    if current_turn_ref is None or current_turn_ref <= 0 or current_turn_ref >= len(session_messages):
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
    """Return a provider-only factual marker for a token-limited model partial.

    The partial assistant bytes themselves remain exact model output. The marker is
    explicitly labelled as runtime provenance and is attached only to the ephemeral
    provider view of the current genuine-human message. Durable human input remains
    byte-exact. It contains no directive about whether/how to continue; the model
    keeps that decision.
    """
    if not isinstance(state, dict) or state.get("provider_truncated") is not True:
        return ""
    finish_reason = str(state.get("finish_reason") or "")[:80]
    payload = {
        "previous_assistant_output_truncated": True,
        "previous_assistant_output_complete": False,
        "partial_output_persisted": True,
        "finish_reason": finish_reason,
    }
    return "[runtime_continuity] " + json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    )


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
    if current_turn_ref is None or current_turn_ref < 0 or current_turn_ref >= len(session_messages):
        return built, {"applied": False, "reason": "no_current_turn"}
    current = session_messages[current_turn_ref]
    if not is_human_user_message(current):
        return built, {"applied": False, "reason": "not_human_ingress"}
    # Initial-human-build only.  Once this turn has produced any assistant/tool
    # protocol message, its native append order is authoritative.  Re-appending the
    # user at the tail after assistant(tool_calls)->tool would corrupt provider wire.
    if any(
        getattr(message, "role", "") in {"assistant", "tool"}
        for message in session_messages[current_turn_ref + 1 :]
    ):
        return built, {"applied": False, "reason": "turn_already_advanced"}
    user_idx = _current_user_wire_index(built, current)
    if user_idx is None:
        return built, {"applied": False, "reason": "current_user_not_in_wire"}

    source = "current_user_only"
    assistant_wire = _resume_message(interruption_resume)
    runtime_fact = _resume_runtime_fact(interruption_resume)
    dialogue_pairs = recent_completed_dialogue_pairs(session_messages, current_turn_ref)
    dialogue_wires = [
        (user.to_llm_dict(), assistant.to_llm_dict()) for user, assistant in dialogue_pairs
    ]
    if assistant_wire is not None:
        assert interruption_resume is not None
        source = str(interruption_resume.get("source") or "interruption_resume")
    elif dialogue_wires:
        source = "recent_dialogue_window"

    before = list(built[:user_idx])
    after_user = list(built[user_idx + 1 :])
    current_wire = dict(built[user_idx])

    # Remove already-visible exact dialogue wires before re-appending the bounded
    # chronological window. This changes representation only, never durable history.
    for user_wire, model_wire in reversed(dialogue_wires):
        for wire in (model_wire, user_wire):
            for idx in range(len(before) - 1, -1, -1):
                item = before[idx]
                if (
                    item.get("role") == wire.get("role")
                    and str(item.get("content") or "") == str(wire.get("content") or "")
                    and item.get("tool_calls") == wire.get("tool_calls")
                ):
                    before.pop(idx)
                    break

    # Any build-time dynamic/program material that appeared after current human is
    # moved ahead of recent dialogue. Exact current human ingress remains final.
    out = before + after_user
    for user_wire, model_wire in dialogue_wires:
        out.append(dict(user_wire))
        out.append(dict(model_wire))
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
        "rehydrated": bool(dialogue_wires or assistant_wire is not None),
        "runtime_fact": bool(runtime_fact),
        "dialogue_pairs": len(dialogue_wires),
    }
