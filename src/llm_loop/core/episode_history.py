"""Resolved-episode lifecycle projection.

Storage truth remains untouched.  A message becomes provider-retirable only
after its completed episode has been durably indexed and the session message is
annotated with the stable episode ref.
"""

from __future__ import annotations

import bisect
import logging
import re
from typing import Any

from llm_loop.core.message import Message
from llm_loop.core.reference_injection import is_human_user_message
from llm_loop.memory.episode import EpisodeStore, stable_episode_ref

logger = logging.getLogger(__name__)


RESOLVED_EPISODE_REF_KEY = "resolved_episode_ref"
EPISODE_STATE_KEY = "episode_state"
EPISODE_STATE_RESOLVED = "resolved"
EPISODE_KEEP_PROVIDER_KEY = "resolved_episode_keep_provider"
EPISODE_RESOLUTION_CANDIDATE_KEY = "episode_resolution_candidate"

_DURABLE_USER_RE = re.compile(
    r"(?:以后|今后|从现在开始|往后|后续(?:都|一律|始终)|始终|永远|长期|不要再|"
    r"作为(?:默认|长期)?(?:规则|约束|偏好)|记住(?:这个|这条)?(?:规则|约束|偏好)|"
    r"\b(?:from now on|going forward|for future|standing rule|persistent constraint|"
    r"remember this (?:rule|constraint|preference)|(?:always|never)\s+"
    r"(?:use|do|ask|show|include|modify|change|stage|reload|run|call|write|read|"
    r"treat|assume|keep|preserve|delete|remove))\b)",
    re.IGNORECASE,
)


def _metadata(message: Message) -> dict[str, Any]:
    md = message.metadata
    return md if isinstance(md, dict) else {}


def resolved_episode_ref(message: Message) -> str:
    return str(_metadata(message).get(RESOLVED_EPISODE_REF_KEY) or "")


def is_resolved_episode_message(message: Message) -> bool:
    return bool(resolved_episode_ref(message))


def provider_view_without_resolved_episodes(messages: list[Message]) -> list[Message]:
    """Project working context by retiring only durably indexed episodes."""

    return [
        m
        for m in messages
        if not is_resolved_episode_message(m)
        or bool(_metadata(m).get(EPISODE_KEEP_PROVIDER_KEY))
    ]


def has_explicit_durable_user_instruction(message: Message) -> bool:
    """Conservative lexical guard for standing user instructions.

    This is deliberately narrow.  It does not try to infer every project
    decision; those remain retrievable via episode/memory search.  It protects
    explicit cross-turn behavioural constraints from being hidden merely
    because the surrounding Q&A episode has completed.
    """

    return is_human_user_message(message) and bool(_DURABLE_USER_RE.search(message.content or ""))


def filtered_anchor_from_original(kept_original_indices: list[int], original_anchor: int) -> int:
    """Translate a persisted session index into a filtered provider-view index.

    The anchor is a boundary: when the exact original message has retired, the
    first surviving message at or after that boundary is the correct filtered
    start. ``bisect_left`` expresses that contract directly.
    """

    anchor = max(0, int(original_anchor or 0))
    if anchor <= 0 or not kept_original_indices:
        return 0
    return bisect.bisect_left(kept_original_indices, anchor)


def original_anchor_from_filtered(
    kept_original_indices: list[int], filtered_anchor: int, *, original_length: int
) -> int:
    """Translate a provider-view anchor back into the persisted session index."""

    anchor = max(0, int(filtered_anchor or 0))
    if anchor <= 0:
        return 0
    if anchor >= len(kept_original_indices):
        return max(0, int(original_length))
    return int(kept_original_indices[anchor])


def _last_assistant_index(messages: list[Message], start: int, end_exclusive: int) -> int | None:
    for idx in range(end_exclusive - 1, start, -1):
        if messages[idx].role == "assistant":
            return idx
    return None


def _completed_model_answer(message: Message) -> bool:
    """Only explicitly resolved current-format answers are safe to retire.

    ``run_end_reason=completed`` alone is insufficient: provider-truncated
    responses can still exit the loop normally.  The engine therefore stamps a
    dedicated candidate bit only for a non-empty, non-truncated model answer.
    Legacy/ambiguous messages without that proof fail-open and remain visible.
    """

    if message.role != "assistant":
        return False
    md = _metadata(message)
    return (
        md.get("run_end_reason") == "completed"
        and md.get("answer_origin") == "model"
        and md.get(EPISODE_RESOLUTION_CANDIDATE_KEY) is True
    )


def _mark_range(messages: list[Message], start: int, end_inclusive: int, ref: str) -> None:
    for idx in range(start, end_inclusive + 1):
        message = messages[idx]
        md = dict(_metadata(message))
        md[RESOLVED_EPISODE_REF_KEY] = ref
        md[EPISODE_STATE_KEY] = EPISODE_STATE_RESOLVED
        if idx == start and has_explicit_durable_user_instruction(message):
            md[EPISODE_KEEP_PROVIDER_KEY] = True
        message.metadata = md


def _index_range(
    store: EpisodeStore,
    session_id: str,
    messages: list[Message],
    *,
    start: int,
    end_inclusive: int,
    resolution_proven: bool = False,
) -> str | None:
    if start < 0 or end_inclusive < start or end_inclusive >= len(messages):
        return None
    user_message = messages[start]
    final_message = messages[end_inclusive]
    if not is_human_user_message(user_message):
        return None
    if not _completed_model_answer(final_message) and not resolution_proven:
        return None
    existing_ref = resolved_episode_ref(user_message)
    ref = existing_ref or stable_episode_ref(session_id, user_message, start)
    store.index_episode(
        session_id,
        ref=ref,
        user_seq=start,
        raw_messages=list(messages[start : end_inclusive + 1]),
    )
    _mark_range(messages, start, end_inclusive, ref)
    return ref


def _legacy_resolution_event_indices(
    event_store: Any | None,
    session_id: str,
    messages: list[Message],
) -> set[int]:
    """Return legacy final-answer indices proven by durable event correlation.

    Pre-R8.5 ``run_end_reason=completed`` metadata alone is not enough: older
    providers could truncate while the loop still reached its normal exit.  A
    legacy answer is therefore accepted only when one event-log run segment has
    exactly one matching final assistant append and its following ``run.end``
    says completed + not truncated with a matching answer preview.  Corrupt or
    ambiguous logs deny the whole legacy migration path for that session.
    """

    if event_store is None or not session_id:
        return set()
    try:
        events = list(event_store.read(session_id) or [])
    except Exception:  # noqa: BLE001 — missing audit proof means fail-open visibility
        logger.warning(
            "legacy resolved proof 读取失败（保留 provider 可见）: sid=%s",
            session_id,
            exc_info=True,
        )
        return set()
    if int(getattr(event_store, "last_read_skipped", 0) or 0) > 0:
        logger.warning(
            "legacy resolved proof 含损坏事件（保留 provider 可见）: sid=%s skipped=%s",
            session_id,
            getattr(event_store, "last_read_skipped", 0),
        )
        return set()

    proven: set[int] = set()
    segment: list[Any] = []
    for event in events:
        if str(getattr(event, "type", "")) != "run.end":
            segment.append(event)
            continue

        end_payload = getattr(event, "payload", None) or {}
        if (
            end_payload.get("reason") == "completed"
            and end_payload.get("truncated") is False
            and str(end_payload.get("answer_preview") or "")
        ):
            candidates: list[int] = []
            for candidate in segment:
                if str(getattr(candidate, "type", "")) != "message.appended":
                    continue
                payload = getattr(candidate, "payload", None) or {}
                metadata = payload.get("metadata") or {}
                if (
                    payload.get("role") != "assistant"
                    or metadata.get("answer_origin") != "model"
                    or metadata.get("run_end_reason") != "completed"
                ):
                    continue
                raw_index = payload.get("index")
                if raw_index is None:
                    continue
                try:
                    index = int(raw_index)
                except (TypeError, ValueError):
                    continue
                if index < 0 or index >= len(messages):
                    continue
                saved = messages[index]
                saved_md = _metadata(saved)
                # Current-format messages already have the stronger candidate bit;
                # this event path exists only to migrate legacy records.
                if EPISODE_RESOLUTION_CANDIDATE_KEY in saved_md:
                    continue
                content = str(payload.get("content") or "")
                saved_content = str(saved.content or "")
                if (
                    saved.role != "assistant"
                    or saved_md.get("answer_origin") != "model"
                    or saved_md.get("run_end_reason") != "completed"
                    or not saved_content.strip()
                    or content != saved_content
                ):
                    continue
                preview = str(end_payload.get("answer_preview") or "")
                expected = saved_content[:200]
                preview_matches = (
                    preview == expected
                    if len(saved_content) >= 200
                    else preview.startswith(saved_content)
                )
                if preview_matches:
                    candidates.append(index)
            if len(candidates) == 1:
                proven.add(candidates[0])
        # A run.end is the hard audit boundary.  Never correlate an assistant
        # append across two runs.
        segment = []
    return proven


def backfill_completed_episodes(
    store: EpisodeStore | None,
    session: Any,
    *,
    event_store: Any | None = None,
) -> list[str]:
    """Index prior completed episodes before the next human run.

    Current-format answers use the R8.5 resolution-candidate bit.  Legacy answers
    may migrate only through the stricter append↔run.end durable event proof.
    Missing/corrupt/ambiguous proof remains provider-visible rather than guessed.
    """

    if store is None:
        return []
    messages: list[Message] = list(getattr(session, "messages", []) or [])
    session_id = str(getattr(session, "session_id", "") or "")
    legacy_proven = _legacy_resolution_event_indices(event_store, session_id, messages)
    human_starts = [idx for idx, m in enumerate(messages) if is_human_user_message(m)]
    refs: list[str] = []
    for pos, start in enumerate(human_starts):
        next_start = human_starts[pos + 1] if pos + 1 < len(human_starts) else len(messages)
        end = _last_assistant_index(messages, start, next_start)
        if end is None:
            continue
        try:
            ref = _index_range(
                store,
                session_id,
                messages,
                start=start,
                end_inclusive=end,
                resolution_proven=end in legacy_proven,
            )
        except Exception:  # noqa: BLE001 — one bad legacy episode must not block ingress
            # Do not partially mark a range if the durable index could not be
            # proven; leave the old episode visible and record the reason.
            logger.warning(
                "resolved episode backfill 失败（保留 provider 可见）: sid=%s start=%d end=%d",
                getattr(session, "session_id", ""),
                start,
                end,
                exc_info=True,
            )
            continue
        if ref:
            refs.append(ref)
    return refs


def index_current_completed_episode(
    store: EpisodeStore | None,
    session: Any,
    *,
    turn_ref: int | None,
    final_answer_index: int,
) -> str | None:
    """Index the just-completed run before session persistence.

    The final assistant metadata itself proves whether the run is completed;
    callers do not pass a second completion flag that could drift from storage
    truth.
    """

    if store is None or turn_ref is None:
        return None
    messages: list[Message] = getattr(session, "messages", []) or []
    return _index_range(
        store,
        str(getattr(session, "session_id", "") or ""),
        messages,
        start=int(turn_ref),
        end_inclusive=int(final_answer_index),
    )
