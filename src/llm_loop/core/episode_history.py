"""Resolved-episode lifecycle projection.

Storage truth remains untouched.  A message becomes provider-retirable only
after its completed episode has been durably indexed and the session message is
annotated with the stable episode ref.
"""

from __future__ import annotations

import bisect
import logging
import os
import re
from dataclasses import dataclass, replace
from typing import Any

from llm_loop.core.message import Message, MessageSource
from llm_loop.core.reference_injection import is_human_user_message
from llm_loop.feedback.honesty import PROGRAM_FEEDBACK_PREFIXES
from llm_loop.memory.episode import (
    EpisodeStore,
    stable_closed_tool_span_ref,
    stable_episode_ref,
    stable_tool_span_ref,
)

logger = logging.getLogger(__name__)


RESOLVED_EPISODE_REF_KEY = "resolved_episode_ref"
EPISODE_STATE_KEY = "episode_state"
EPISODE_STATE_RESOLVED = "resolved"
EPISODE_KEEP_PROVIDER_KEY = "resolved_episode_keep_provider"
EPISODE_RESOLUTION_CANDIDATE_KEY = "episode_resolution_candidate"
CONSUMED_TOOL_SPAN_REF_KEY = "consumed_tool_span_ref"
CONSUMED_TOOL_SPAN_STATE_KEY = "tool_span_state"
CONSUMED_TOOL_SPAN_STATE = "consumed"
CLOSED_TOOL_SPAN_REF_KEY = "closed_tool_span_ref"
CLOSED_TOOL_SPAN_STATE = "closed"

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


def consumed_tool_span_ref(message: Message) -> str:
    return str(_metadata(message).get(CONSUMED_TOOL_SPAN_REF_KEY) or "")


def is_consumed_tool_span_message(message: Message) -> bool:
    return bool(consumed_tool_span_ref(message))


def closed_tool_span_ref(message: Message) -> str:
    return str(_metadata(message).get(CLOSED_TOOL_SPAN_REF_KEY) or "")


def is_closed_tool_span_message(message: Message) -> bool:
    return bool(closed_tool_span_ref(message))


def provider_message_visible(message: Message) -> bool:
    """Return whether one persisted message belongs in default provider history."""

    # Interrupted assistant bytes are durable storage/audit truth, not a completed
    # conversational turn.  In particular, a direct client disconnect can persist
    # genuine model partial text; replaying that partial as a normal assistant answer
    # on the next request silently upgrades an incomplete response to completion.
    if _metadata(message).get("llm_interrupted") is True:
        return False
    # R8.22: a historical user turn does not keep prompt authority merely
    # because its text contains standing-rule language.  Exact source text
    # remains durable in EpisodeStore and can be hydrated on demand.
    # ``resolved_episode_keep_provider`` is now legacy storage metadata only.
    return not (
        is_consumed_tool_span_message(message)
        or is_closed_tool_span_message(message)
        or is_resolved_episode_message(message)
    )


def _working_set_receipts_enabled() -> bool:
    raw = (os.environ.get("LFL_TOOL_WORKING_SET_RECEIPTS", "0") or "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _working_set_batch_chars() -> int:
    """Mechanical fold size; batching amortizes prefix rewrites without judging relevance."""

    raw = (os.environ.get("LFL_TOOL_WORKING_SET_BATCH_CHARS", "32768") or "32768").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 32768
    return max(4096, min(value, 1_048_576))


def _working_set_grace_groups() -> int:
    """Mechanical recency grace; keep newest exposed tool groups raw for continuity."""

    raw = (os.environ.get("LFL_TOOL_WORKING_SET_GRACE_GROUPS", "0") or "0").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 0
    return max(0, min(value, 64))


def _is_model_followup(message: Message) -> bool:
    """Return whether a later real model turn proves the prior tool bytes were exposed once."""

    if message.role != "assistant":
        return False
    md = _metadata(message)
    if md.get("answer_origin") == "program" or message.source == MessageSource.SYSTEM:
        return False
    if message.tool_calls:
        return True
    return _is_tool_consumer(message)


def _tool_evidence_receipt(message: Message) -> Message | None:
    """Return a protocol-preserving compact view for one durably recoverable tool result."""

    if message.role != "tool":
        return None
    md = _metadata(message)
    if str(md.get("recoverability_status") or "") != "recorded":
        return None
    ref = str(md.get("evidence_ref") or "").strip()
    if not ref:
        return None
    status = getattr(message.status, "value", None) or str(message.status or "unknown")
    source = str(md.get("evidence_source_label") or message.tool_name or "")
    coverage = str(md.get("evidence_coverage_label") or "")
    representation = str(md.get("evidence_representation") or "")
    complete = md.get("evidence_projection_complete")
    facts = [
        f"[状态: {status}] [tool_result_receipt]",
        "prior_full_result_exposed=true",
        f"evidence_ref={ref}",
    ]
    if source:
        facts.append(f"source={source}")
    if coverage:
        facts.append(f"coverage={coverage}")
    if representation:
        facts.append(f"representation={representation}")
    if complete is not None:
        facts.append(f"projection_complete={str(bool(complete)).lower()}")
    origin = md.get("evidence_origin_facts")
    if isinstance(origin, dict):
        acquired_at = str(origin.get("acquired_at") or "").strip()
        version_policy = str(origin.get("source_version_policy") or "").strip()
        if acquired_at:
            facts.append(f"acquired_at={acquired_at}")
        if version_policy:
            facts.append(f"version_policy={version_policy}")
    # Receipt stays deliberately thin. Full source kind/version token/provenance remain
    # durably available through read_evidence; the folded view only carries the two
    # origin facts that help the model notice temporal/applicability risk.
    facts.append("task_applicability=not_evaluated")
    facts.append("recovery_tool=read_evidence")
    projected_md = dict(md)
    projected_md["working_set_projection"] = "evidence_receipt"
    return replace(message, content=" ".join(facts), metadata=projected_md)


@dataclass(frozen=True, slots=True)
class ToolWorkingSetProjectionStats:
    """Prompt-neutral facts about one active-run representation projection."""

    enabled: bool
    batch_chars: int
    raw_tool_chars: int
    projected_tool_chars: int
    receipt_chars: int
    folded_results: int
    folded_groups: int
    grace_groups: int
    grace_raw_chars: int
    grace_results: int
    pending_raw_chars: int
    pending_results: int
    latest_raw_chars: int
    fold_boundaries: tuple[int, ...]


def project_active_tool_working_set_with_stats(
    messages: list[Message],
) -> tuple[list[Message], ToolWorkingSetProjectionStats]:
    """Project active-run tool results and return factual, non-prompt telemetry.

    ``fold_boundaries`` are message indices at the end of each newly completed coarse
    batch in the current projection. They describe representation mechanics only; they
    do not claim that any evidence is important, stale, sufficient, or safe to ignore.
    """

    enabled = _working_set_receipts_enabled()
    batch_chars = _working_set_batch_chars() if enabled else 0
    grace_groups = _working_set_grace_groups() if enabled else 0
    raw_tool_chars = sum(len(message.content or "") for message in messages if message.role == "tool")
    if not enabled or not messages:
        return messages, ToolWorkingSetProjectionStats(
            enabled=enabled,
            batch_chars=batch_chars,
            raw_tool_chars=raw_tool_chars,
            projected_tool_chars=raw_tool_chars,
            receipt_chars=0,
            folded_results=0,
            folded_groups=0,
            grace_groups=grace_groups,
            grace_raw_chars=0,
            grace_results=0,
            pending_raw_chars=0,
            pending_results=0,
            latest_raw_chars=0,
            fold_boundaries=(),
        )
    human_starts = [idx for idx, message in enumerate(messages) if is_human_user_message(message)]
    if not human_starts:
        return messages, ToolWorkingSetProjectionStats(
            enabled=True,
            batch_chars=batch_chars,
            raw_tool_chars=raw_tool_chars,
            projected_tool_chars=raw_tool_chars,
            receipt_chars=0,
            folded_results=0,
            folded_groups=0,
            grace_groups=grace_groups,
            grace_raw_chars=0,
            grace_results=0,
            pending_raw_chars=0,
            pending_results=0,
            latest_raw_chars=0,
            fold_boundaries=(),
        )
    start = human_starts[-1]
    end = len(messages)
    projected = list(messages)
    pending: list[tuple[int, Message]] = []
    pending_chars = 0
    pending_group_count = 0
    grace_queue: list[tuple[list[tuple[int, Message]], int]] = []
    folded_results = 0
    folded_groups = 0
    receipt_chars = 0
    fold_boundaries: list[int] = []
    latest_raw_chars = 0
    cursor = start + 1
    while cursor < end:
        message = messages[cursor]
        if message.role != "assistant" or not message.tool_calls:
            cursor += 1
            continue
        group_end = _tool_group_end(messages, cursor, end)
        if group_end is None:
            cursor += 1
            continue
        later_model_turn = any(_is_model_followup(messages[idx]) for idx in range(group_end, end))
        group_raw_chars = sum(
            len(messages[idx].content or "")
            for idx in range(cursor + 1, group_end)
            if messages[idx].role == "tool"
        )
        if not later_model_turn:
            latest_raw_chars += group_raw_chars
        else:
            group_receipts: list[tuple[int, Message]] = []
            group_chars = 0
            for idx in range(cursor + 1, group_end):
                receipt = _tool_evidence_receipt(messages[idx])
                if receipt is not None:
                    group_receipts.append((idx, receipt))
                    group_chars += len(messages[idx].content or "")
            if group_receipts:
                grace_queue.append((group_receipts, group_chars))
            while len(grace_queue) > grace_groups:
                promoted_receipts, promoted_chars = grace_queue.pop(0)
                pending.extend(promoted_receipts)
                pending_chars += promoted_chars
                pending_group_count += 1
                if pending and pending_chars >= batch_chars:
                    for idx, receipt in pending:
                        projected[idx] = receipt
                        receipt_chars += len(receipt.content or "")
                    folded_results += len(pending)
                    folded_groups += pending_group_count
                    fold_boundaries.append(group_end)
                    pending = []
                    pending_chars = 0
                    pending_group_count = 0
        cursor = group_end
    projected_tool_chars = sum(
        len(message.content or "") for message in projected if message.role == "tool"
    )
    grace_raw_chars = sum(chars for _receipts, chars in grace_queue)
    grace_results = sum(len(receipts) for receipts, _chars in grace_queue)
    return projected, ToolWorkingSetProjectionStats(
        enabled=True,
        batch_chars=batch_chars,
        raw_tool_chars=raw_tool_chars,
        projected_tool_chars=projected_tool_chars,
        receipt_chars=receipt_chars,
        folded_results=folded_results,
        folded_groups=folded_groups,
        grace_groups=grace_groups,
        grace_raw_chars=grace_raw_chars,
        grace_results=grace_results,
        pending_raw_chars=pending_chars,
        pending_results=len(pending),
        latest_raw_chars=latest_raw_chars,
        fold_boundaries=tuple(fold_boundaries),
    )


def project_active_tool_working_set(messages: list[Message]) -> list[Message]:
    """Compatibility wrapper returning only the provider projection."""

    projected, _stats = project_active_tool_working_set_with_stats(messages)
    return projected


def provider_view_without_resolved_episodes(messages: list[Message]) -> list[Message]:
    """Project working context after durable lifecycle retirement.

    The historical public name is kept for compatibility.  Besides whole
    resolved episodes, R8.20 retires durably indexed tool spans across completed
    answer boundaries.  Optional active-run receipts additionally compress only
    the representation of older, already-exposed, durably recoverable tool results.
    """

    return [m for m in messages if provider_message_visible(m)]


def has_explicit_durable_user_instruction(message: Message) -> bool:
    """Conservative lexical detector for standing user-instruction wording.

    R8.22 deliberately separates detection from prompt authority.  This helper
    may still be useful for audit/migration, but a match never means that the
    full historical source message must remain provider-visible.
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


def _tool_group_end(messages: list[Message], start: int, end_exclusive: int) -> int | None:
    """Return the exclusive end of one exact assistant(tool_calls)->tool group."""

    if start < 0 or start >= end_exclusive:
        return None
    declaration = messages[start]
    if declaration.role != "assistant" or not declaration.tool_calls:
        return None
    declared = [str(call.get("id") or "") for call in declaration.tool_calls if isinstance(call, dict)]
    if not declared or any(not call_id for call_id in declared) or len(set(declared)) != len(declared):
        return None
    idx = start + 1
    receipts: list[str] = []
    while idx < end_exclusive and messages[idx].role == "tool":
        receipts.append(str(messages[idx].tool_call_id or ""))
        idx += 1
    if (
        len(receipts) != len(declared)
        or any(not receipt for receipt in receipts)
        or set(receipts) != set(declared)
    ):
        return None
    return idx


def _is_tool_consumer(message: Message) -> bool:
    """A real non-tool model answer proves prior tool evidence was consumed."""

    if message.role != "assistant" or message.tool_calls or not str(message.content or "").strip():
        return False
    md = _metadata(message)
    if md.get("answer_origin") == "program" or message.source == MessageSource.SYSTEM:
        return False
    text = str(message.content or "")
    if text.startswith(PROGRAM_FEEDBACK_PREFIXES):
        return False
    # Current format explicitly identifies model answers.  Legacy sessions often
    # lack answer_origin but retain model_used/source=user; accept those while the
    # program-feedback guards above deny known synthetic finals.
    return md.get("answer_origin") == "model" or bool(message.model_used) or message.source == MessageSource.USER


def _mark_consumed_tool_indices(messages: list[Message], indices: list[int], ref: str) -> None:
    for idx in indices:
        message = messages[idx]
        md = dict(_metadata(message))
        md[CONSUMED_TOOL_SPAN_REF_KEY] = ref
        md[CONSUMED_TOOL_SPAN_STATE_KEY] = CONSUMED_TOOL_SPAN_STATE
        message.metadata = md


def _mark_closed_tool_indices(messages: list[Message], indices: list[int], ref: str) -> None:
    for idx in indices:
        message = messages[idx]
        md = dict(_metadata(message))
        md[CLOSED_TOOL_SPAN_REF_KEY] = ref
        md[CONSUMED_TOOL_SPAN_STATE_KEY] = CLOSED_TOOL_SPAN_STATE
        message.metadata = md


def _closed_attempt_event_ranges(
    event_store: Any | None,
    session_id: str,
    messages: list[Message],
) -> list[tuple[int, int, str]]:
    """Return event-proven prior failed-run ranges as (user, terminal, reason)."""

    if event_store is None or not session_id:
        return []
    try:
        events = list(event_store.read(session_id) or [])
    except Exception:  # noqa: BLE001 — missing audit proof means keep provider-visible
        logger.warning(
            "closed attempt proof 读取失败（保留 provider 可见）: sid=%s",
            session_id,
            exc_info=True,
        )
        return []
    if int(getattr(event_store, "last_read_skipped", 0) or 0) > 0:
        logger.warning(
            "closed attempt proof 含损坏事件（保留 provider 可见）: sid=%s skipped=%s",
            session_id,
            getattr(event_store, "last_read_skipped", 0),
        )
        return []

    proven: list[tuple[int, int, str]] = []
    segment: list[Any] = []
    for event in events:
        if str(getattr(event, "type", "")) != "run.end":
            segment.append(event)
            continue
        end_payload = getattr(event, "payload", None) or {}
        reason = str(end_payload.get("reason") or "")
        if reason and reason != "completed":
            human_indices: list[int] = []
            terminal_indices: list[int] = []
            for candidate in segment:
                if str(getattr(candidate, "type", "")) != "message.appended":
                    continue
                payload = getattr(candidate, "payload", None) or {}
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
                if (
                    str(payload.get("role") or "") != saved.role
                    or str(payload.get("content") or "") != str(saved.content or "")
                ):
                    continue
                md = _metadata(saved)
                if is_human_user_message(saved) and md.get("ingress_delegated") is not True:
                    human_indices.append(index)
                if (
                    saved.role == "assistant"
                    and not saved.tool_calls
                    and md.get("answer_origin") == "program"
                    and md.get("llm_interrupted") is not True
                    and str(md.get("run_end_reason") or "") == reason
                ):
                    terminal_indices.append(index)
            if (
                len(human_indices) == 1
                and len(terminal_indices) == 1
                and human_indices[0] < terminal_indices[0]
            ):
                proven.append((human_indices[0], terminal_indices[0], reason))
        segment = []
    return proven


def backfill_consumed_tool_spans(store: EpisodeStore | None, session: Any) -> list[str]:
    """Durably index and retire raw tool evidence already consumed by a model answer.

    This lifecycle is intentionally narrower than whole-episode resolution.  It
    never retires the human instruction or the consuming assistant answer, and it
    never touches an incomplete/current tool-followup chain.  Storage/session
    truth stays exact; only later provider projection omits marked tool material.
    """

    if store is None:
        return []
    messages: list[Message] = list(getattr(session, "messages", []) or [])
    session_id = str(getattr(session, "session_id", "") or "")
    human_starts = [idx for idx, message in enumerate(messages) if is_human_user_message(message)]
    refs: list[str] = []

    for pos, start in enumerate(human_starts):
        next_start = human_starts[pos + 1] if pos + 1 < len(human_starts) else len(messages)
        consumer: int | None = None
        for idx in range(start + 1, next_start):
            if _is_tool_consumer(messages[idx]):
                consumer = idx
                break
        if consumer is None:
            continue

        tool_indices: list[int] = []
        call_ids: list[str] = []
        cursor = start + 1
        invalid_group = False
        while cursor < consumer:
            message = messages[cursor]
            if message.role == "assistant" and message.tool_calls:
                group_end = _tool_group_end(messages, cursor, consumer)
                if group_end is None:
                    invalid_group = True
                    break
                group_indices = list(range(cursor, group_end))
                # Whole resolved episodes already have a stronger retirement/ref;
                # do not create a duplicate tool-span record for those groups.
                if not all(is_resolved_episode_message(messages[idx]) for idx in group_indices):
                    if any(is_resolved_episode_message(messages[idx]) for idx in group_indices):
                        invalid_group = True
                        break
                    # Closed is a distinct terminal state: a later unrelated model
                    # answer must never rewrite a failed attempt as "consumed".
                    if all(is_closed_tool_span_message(messages[idx]) for idx in group_indices):
                        cursor = group_end
                        continue
                    if any(is_closed_tool_span_message(messages[idx]) for idx in group_indices):
                        invalid_group = True
                        break
                    tool_indices.extend(group_indices)
                    call_ids.extend(
                        str(call.get("id") or "")
                        for call in (message.tool_calls or [])
                        if isinstance(call, dict)
                    )
                cursor = group_end
                continue
            cursor += 1

        if invalid_group or not tool_indices:
            continue
        existing_refs = {consumed_tool_span_ref(messages[idx]) for idx in tool_indices}
        existing_refs.discard("")
        if len(existing_refs) > 1:
            continue
        if existing_refs and all(is_consumed_tool_span_message(messages[idx]) for idx in tool_indices):
            refs.extend(sorted(existing_refs))
            continue

        ref = next(iter(existing_refs), "") or stable_tool_span_ref(
            session_id,
            messages[start],
            start,
            consumer,
            call_ids,
        )
        raw_messages = [messages[start], *[messages[idx] for idx in tool_indices], messages[consumer]]
        try:
            store.index_tool_span(
                session_id,
                ref=ref,
                user_seq=start,
                consumer_seq=consumer,
                raw_messages=raw_messages,
            )
        except Exception:  # noqa: BLE001 — durable proof failure means keep provider-visible
            logger.warning(
                "consumed tool span 索引失败（保留 provider 可见）: sid=%s start=%d consumer=%d",
                session_id,
                start,
                consumer,
                exc_info=True,
            )
            continue
        _mark_consumed_tool_indices(messages, tool_indices, ref)
        refs.append(ref)
    return refs


def backfill_closed_tool_attempts(
    store: EpisodeStore | None,
    session: Any,
    *,
    event_store: Any | None = None,
) -> list[str]:
    """Durably retire raw tool protocol from prior event-proven failed runs.

    This is distinct from both resolved episodes and consumed tool evidence.  The
    original human instruction and terminal failure assistant remain visible; only
    complete assistant(tool_calls)->tool groups are retired after durable indexing.
    """

    if store is None:
        return []
    messages: list[Message] = list(getattr(session, "messages", []) or [])
    session_id = str(getattr(session, "session_id", "") or "")
    refs: list[str] = []
    # Give the immediately previous interrupted human turn exactly one genuine-user
    # continuation opportunity before retiring its raw tool protocol.  This is purely
    # structural (last human + durable llm_interrupted marker), not a guess that the
    # next user text means "continue".  On the following human ingress the last-human
    # index has advanced, so an unconsumed older failed span becomes normally closable.
    last_human_index = next(
        (
            idx
            for idx in range(len(messages) - 1, -1, -1)
            if is_human_user_message(messages[idx])
        ),
        None,
    )
    for start, terminal, reason in _closed_attempt_event_ranges(
        event_store, session_id, messages
    ):
        if start == last_human_index and any(
            _metadata(messages[idx]).get("llm_interrupted") is True
            for idx in range(start + 1, min(terminal + 1, len(messages)))
        ):
            continue
        tool_indices: list[int] = []
        call_ids: list[str] = []
        preexisting_refs: set[str] = set()
        cursor = start + 1
        invalid_group = False
        while cursor < terminal:
            message = messages[cursor]
            if message.role != "assistant" or not message.tool_calls:
                cursor += 1
                continue
            group_end = _tool_group_end(messages, cursor, terminal)
            if group_end is None:
                invalid_group = True
                break
            group_indices = list(range(cursor, group_end))
            closed_flags = [is_closed_tool_span_message(messages[idx]) for idx in group_indices]
            if all(closed_flags):
                preexisting_refs.update(
                    closed_tool_span_ref(messages[idx]) for idx in group_indices
                )
                cursor = group_end
                continue
            if any(closed_flags):
                invalid_group = True
                break
            prior_retired = [
                is_resolved_episode_message(messages[idx])
                or is_consumed_tool_span_message(messages[idx])
                for idx in group_indices
            ]
            if all(prior_retired):
                cursor = group_end
                continue
            if any(prior_retired):
                invalid_group = True
                break
            tool_indices.extend(group_indices)
            call_ids.extend(
                str(call.get("id") or "")
                for call in (message.tool_calls or [])
                if isinstance(call, dict)
            )
            cursor = group_end

        if invalid_group:
            continue
        if preexisting_refs and tool_indices:
            # Partial prior mutation is ambiguous; leave unmarked material visible.
            continue
        if not tool_indices:
            refs.extend(sorted(ref for ref in preexisting_refs if ref))
            continue

        ref = stable_closed_tool_span_ref(
            session_id,
            messages[start],
            start,
            terminal,
            reason,
            call_ids,
        )
        raw_messages = [
            messages[start],
            *[messages[idx] for idx in tool_indices],
            messages[terminal],
        ]
        try:
            store.index_closed_tool_span(
                session_id,
                ref=ref,
                user_seq=start,
                terminal_seq=terminal,
                terminal_reason=reason,
                raw_messages=raw_messages,
            )
        except Exception:  # noqa: BLE001 — durable proof failure => keep visible
            logger.warning(
                "closed tool span 索引失败（保留 provider 可见）: sid=%s start=%d terminal=%d reason=%s",
                session_id,
                start,
                terminal,
                reason,
                exc_info=True,
            )
            continue
        _mark_closed_tool_indices(messages, tool_indices, ref)
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
