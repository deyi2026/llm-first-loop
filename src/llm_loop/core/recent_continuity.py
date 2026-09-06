"""Prompt-tail continuity for the immediately adjacent human/model interaction.

This module is deliberately structural.  It never classifies whether the user text
"looks like" an answer, continuation, or new task.  On an initial genuine-human
round it only guarantees that the latest real model assistant (or one-shot exact
interrupted model state) and the current human ingress form the final prompt suffix.
Older resolved material remains indexed/retrievable and program-origin material may
exist earlier in the prompt, but nothing program-authored is allowed to split this
adjacent interaction pair.
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
    if not text_tail and not reasoning_tail:
        return None
    out: dict[str, Any] = {"role": "assistant", "content": text_tail}
    if reasoning_tail:
        out["reasoning_content"] = reasoning_tail
    return out


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
    current_text = str(getattr(current, "content", "") or "")
    user_idx = next(
        (
            idx
            for idx in range(len(built) - 1, -1, -1)
            if built[idx].get("role") == "user"
            and str(built[idx].get("content") or "") == current_text
        ),
        None,
    )
    if user_idx is None:
        return built, {"applied": False, "reason": "current_user_not_in_wire"}

    source = "current_user_only"
    assistant_wire = _resume_message(interruption_resume)
    runtime_fact = _resume_runtime_fact(interruption_resume)
    candidate = None
    if assistant_wire is not None:
        # _resume_message() only succeeds for a dict state, but keep the local
        # narrowing explicit so the runtime fact and static contract agree.
        assert interruption_resume is not None
        source = str(interruption_resume.get("source") or "interruption_resume")
    else:
        candidate = latest_model_assistant_before_turn(session_messages, current_turn_ref)
        if candidate is not None:
            source = "recent_model_assistant"
            # Prefer the already-projected wire form (it may contain provider-required
            # reasoning replay).  If R8.5 retired it, rehydrate exact storage form for
            # this one adjacent user turn only.
            candidate_content = str(getattr(candidate, "content", "") or "")
            candidate_calls = getattr(candidate, "tool_calls", None)
            match_idx = next(
                (
                    idx
                    for idx in range(user_idx - 1, -1, -1)
                    if built[idx].get("role") == "assistant"
                    and str(built[idx].get("content") or "") == candidate_content
                    and built[idx].get("tool_calls") == candidate_calls
                ),
                None,
            )
            if match_idx is not None:
                assistant_wire = dict(built[match_idx])
            else:
                assistant_wire = candidate.to_llm_dict()

    before = list(built[:user_idx])
    after_user = list(built[user_idx + 1 :])
    current_wire = dict(built[user_idx])

    # If the prior assistant is already in history, move only its closest matching
    # occurrence; do not duplicate identical content from older unrelated turns.
    removed_existing = False
    if assistant_wire is not None and source == "recent_model_assistant":
        for idx in range(len(before) - 1, -1, -1):
            item = before[idx]
            if (
                item.get("role") == "assistant"
                and str(item.get("content") or "") == str(assistant_wire.get("content") or "")
                and item.get("tool_calls") == assistant_wire.get("tool_calls")
            ):
                before.pop(idx)
                removed_existing = True
                break

    # Any build-time dynamic/program material that appeared after current human is
    # moved ahead of the recent pair.  The exact human ingress remains the final item.
    out = before + after_user
    if runtime_fact:
        current_wire["content"] = (
            f"{current_text}\n\n[provider_runtime_fact—not_human_text]\n{runtime_fact}"
        )
    if assistant_wire is not None:
        out.append(assistant_wire)
    out.append(current_wire)
    return out, {
        "applied": True,
        "source": source,
        "moved_after_user": len(after_user),
        "rehydrated": bool(assistant_wire is not None and not removed_existing),
        "runtime_fact": bool(runtime_fact),
    }
