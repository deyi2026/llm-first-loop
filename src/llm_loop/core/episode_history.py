"""Resolved-episode lifecycle projection.

Storage truth remains untouched.  A message becomes provider-retirable only
after its completed episode has been durably indexed and the session message is
annotated with the stable episode ref.
"""

from __future__ import annotations

import bisect
import hashlib
import json
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
    stable_delegated_span_ref,
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
DELEGATED_SPAN_REF_KEY = "delegated_span_ref"
DELEGATED_SPAN_STATE_KEY = "delegated_span_state"
DELEGATED_SPAN_STATE = "closed"

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


def delegated_span_ref(message: Message) -> str:
    return str(_metadata(message).get(DELEGATED_SPAN_REF_KEY) or "")


def is_closed_delegated_span_message(message: Message) -> bool:
    md = _metadata(message)
    return bool(delegated_span_ref(message)) and md.get(DELEGATED_SPAN_STATE_KEY) == DELEGATED_SPAN_STATE


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
        or is_closed_delegated_span_message(message)
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
    artifact_facts = md.get("artifact_facts")
    if isinstance(artifact_facts, list):
        for artifact in artifact_facts:
            if not isinstance(artifact, dict):
                continue
            artifact_ref = str(artifact.get("artifact_ref") or "").strip()
            artifact_path = str(artifact.get("path") or "").strip()
            artifact_sha = str(artifact.get("sha256") or "").strip()
            if artifact_ref:
                facts.append(f"artifact_ref={artifact_ref}")
            if artifact_path:
                facts.append(f"artifact_path={artifact_path}")
            if artifact_sha:
                facts.append(f"artifact_sha256={artifact_sha}")
    # Receipt stays deliberately thin. Full source kind/version token/provenance remain
    # durably available through read_evidence; the folded view only carries the two
    # origin facts that help the model notice temporal/applicability risk.
    facts.append("task_applicability=not_evaluated")
    facts.append("recovery_tool=read_evidence")
    projected_md = dict(md)
    projected_md["working_set_projection"] = "evidence_receipt"
    return replace(message, content=" ".join(facts), metadata=projected_md)


_EVIDENCE_GROUP_DIGEST_VERSION = 1
_EVIDENCE_ARGS_INLINE_CHARS = 384
_EVIDENCE_ARGS_PREVIEW_CHARS = 192


def _mechanical_status(message: Message) -> str:
    return str(getattr(message.status, "value", None) or message.status or "unknown")


def _canonical_argument(value: Any) -> str:
    """Canonicalize one tool argument value without interpreting its task meaning."""

    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return value
        return json.dumps(decoded, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def _bounded_canonical_argument(value: Any) -> str:
    canonical = _canonical_argument(value)
    if len(canonical) <= _EVIDENCE_ARGS_INLINE_CHARS:
        return canonical
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    preview = canonical[:_EVIDENCE_ARGS_PREVIEW_CHARS]
    return f"sha256={digest};preview={preview}"


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _evidence_protocol_digest(declaration: Message, results: list[Message]) -> str:
    """Stable protocol identity for one exact assistant/tool evidence group."""

    payload = {
        "version": _EVIDENCE_GROUP_DIGEST_VERSION,
        "tool_calls": declaration.tool_calls or [],
        "results": [
            {
                "tool_call_id": str(result.tool_call_id or ""),
                "tool_name": str(result.tool_name or ""),
                "status": _mechanical_status(result),
                "content_sha256": hashlib.sha256((result.content or "").encode("utf-8")).hexdigest(),
            }
            for result in results
        ],
    }
    return f"v{_EVIDENCE_GROUP_DIGEST_VERSION}:" + hashlib.sha256(
        _canonical_json_bytes(payload)
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class _AtomicToolGroupSpan:
    """Lightweight paired current-turn group used by both receipt and S0 identity paths."""

    start: int
    end_exclusive: int
    result_indices: tuple[int, ...]
    exposed: bool


def _collect_active_tool_group_spans(messages: list[Message]) -> tuple[_AtomicToolGroupSpan, ...]:
    """Collect complete current-human-turn tool groups without hashing raw evidence."""

    human_starts = [idx for idx, message in enumerate(messages) if is_human_user_message(message)]
    if not human_starts:
        return ()
    start = human_starts[-1]
    end = len(messages)
    groups: list[_AtomicToolGroupSpan] = []
    cursor = start + 1
    while cursor < end:
        declaration = messages[cursor]
        if declaration.role != "assistant" or not declaration.tool_calls:
            cursor += 1
            continue
        group_end = _tool_group_end(messages, cursor, end)
        if group_end is None:
            cursor += 1
            continue
        result_indices = tuple(
            idx for idx in range(cursor + 1, group_end) if messages[idx].role == "tool"
        )
        groups.append(
            _AtomicToolGroupSpan(
                start=cursor,
                end_exclusive=group_end,
                result_indices=result_indices,
                exposed=any(_is_model_followup(messages[idx]) for idx in range(group_end, end)),
            )
        )
        cursor = group_end
    return tuple(groups)


@dataclass(frozen=True, slots=True)
class EvidenceGroupDescriptor:
    """Model-facing mechanical facts for one complete assistant/tool protocol group."""

    evidence_id: str
    protocol_digest: str
    tool_call_ids: tuple[str, ...]
    tool_names: tuple[str, ...]
    canonical_args: tuple[str, ...]
    raw_chars: int
    result_count: int
    statuses: tuple[str, ...]
    recoverable: bool

    def to_catalog_dict(self) -> dict[str, Any]:
        """Return only the bounded mechanical fields permitted in an evidence catalog."""

        return {
            "id": self.evidence_id,
            "protocol_digest": self.protocol_digest,
            "tool_call_ids": list(self.tool_call_ids),
            "tool_names": list(self.tool_names),
            "canonical_args": list(self.canonical_args),
            "raw_chars": self.raw_chars,
            "result_count": self.result_count,
            "status": list(self.statuses),
            "recoverable": self.recoverable,
        }


@dataclass(frozen=True, slots=True)
class AtomicEvidenceGroup:
    """One complete current-human-turn tool group plus non-model-facing storage indices."""

    descriptor: EvidenceGroupDescriptor
    start: int
    end_exclusive: int
    result_indices: tuple[int, ...]
    exposed: bool


@dataclass(frozen=True, slots=True)
class EvidenceSelectionShadowStats:
    """Prompt-neutral mechanics for a model-produced evidence-ID selection."""

    candidate_set_digest: str
    selected_ids: tuple[str, ...]
    candidate_group_count: int
    candidate_raw_chars: int
    selected_group_count: int
    selected_raw_chars: int
    selected_tool_call_count: int
    unknown_id_count: int
    duplicate_id_count: int
    pairing_valid: bool
    selection_valid: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_set_digest": self.candidate_set_digest,
            "selected_ids": list(self.selected_ids),
            "candidate_group_count": self.candidate_group_count,
            "candidate_raw_chars": self.candidate_raw_chars,
            "selected_group_count": self.selected_group_count,
            "selected_raw_chars": self.selected_raw_chars,
            "selected_tool_call_count": self.selected_tool_call_count,
            "unknown_id_count": self.unknown_id_count,
            "duplicate_id_count": self.duplicate_id_count,
            "pairing_valid": self.pairing_valid,
            "selection_valid": self.selection_valid,
        }


def collect_active_evidence_groups(messages: list[Message]) -> tuple[AtomicEvidenceGroup, ...]:
    """Collect complete current-human-turn tool groups in deterministic transcript order.

    The collector performs protocol identity/pairing work only. It does not rank,
    summarize, or infer relevance/sufficiency. Fold-local IDs are assigned over the
    complete groups visible in this snapshot and therefore restart from ``e1`` for
    each new candidate snapshot.
    """

    groups: list[AtomicEvidenceGroup] = []
    for span in _collect_active_tool_group_spans(messages):
        declaration = messages[span.start]
        results = [messages[idx] for idx in span.result_indices]
        tool_calls = [call for call in (declaration.tool_calls or []) if isinstance(call, dict)]
        tool_call_ids = tuple(str(call.get("id") or "") for call in tool_calls)
        tool_names = tuple(
            str((call.get("function") or {}).get("name") or "")
            if isinstance(call.get("function"), dict)
            else ""
            for call in tool_calls
        )
        canonical_args = tuple(
            _bounded_canonical_argument((call.get("function") or {}).get("arguments"))
            if isinstance(call.get("function"), dict)
            else _bounded_canonical_argument(None)
            for call in tool_calls
        )
        recoverable = bool(results) and all(
            str(_metadata(result).get("recoverability_status") or "") == "recorded"
            and bool(str(_metadata(result).get("evidence_ref") or "").strip())
            for result in results
        )
        descriptor = EvidenceGroupDescriptor(
            evidence_id=f"e{len(groups) + 1}",
            protocol_digest=_evidence_protocol_digest(declaration, results),
            tool_call_ids=tool_call_ids,
            tool_names=tool_names,
            canonical_args=canonical_args,
            raw_chars=sum(len(result.content or "") for result in results),
            result_count=len(results),
            statuses=tuple(_mechanical_status(result) for result in results),
            recoverable=recoverable,
        )
        groups.append(
            AtomicEvidenceGroup(
                descriptor=descriptor,
                start=span.start,
                end_exclusive=span.end_exclusive,
                result_indices=span.result_indices,
                exposed=span.exposed,
            )
        )
    return tuple(groups)


def evidence_candidate_set_digest(groups: tuple[AtomicEvidenceGroup, ...]) -> str:
    """Digest one ordered candidate snapshot without depending on fold-local IDs."""

    payload = {
        "version": _EVIDENCE_GROUP_DIGEST_VERSION,
        "protocol_digests": [group.descriptor.protocol_digest for group in groups],
    }
    return f"v{_EVIDENCE_GROUP_DIGEST_VERSION}:" + hashlib.sha256(
        _canonical_json_bytes(payload)
    ).hexdigest()


_WORKING_STATE_CHECKPOINT_VERSION = 1
_CHECKPOINT_TRUNCATION_REASONS = {
    "length",
    "max_token",
    "max_tokens",
    "max_tokens_reached",
}


@dataclass(frozen=True, slots=True)
class WorkingStateCheckpointResolution:
    """Mechanical eligibility result for one persisted model-authored checkpoint."""

    eligible: bool
    reason: str
    state_text: str = ""
    preserve_group_digests: tuple[str, ...] = ()
    candidate_set_digest: str = ""
    selected_raw_chars: int = 0


def _latest_human_index(messages: list[Message]) -> int | None:
    for idx in range(len(messages) - 1, -1, -1):
        if is_human_user_message(messages[idx]):
            return idx
    return None


def _human_anchor_digest(message: Message) -> str:
    """Stable task-anchor identity that survives JSON/event-log replay."""

    md = _metadata(message)
    payload = {
        "role": message.role,
        "source": message.source.value,
        "content": message.content,
        # Attachments materially change the human ingress while unrelated runtime
        # metadata must not invalidate a checkpoint after replay.
        "attachments": md.get("attachments"),
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def build_working_state_checkpoint(
    *,
    session_id: str,
    messages: list[Message],
    provider_id: str,
    model: str,
    selected_ids: list[str] | tuple[str, ...],
    state_text: str,
    state_char_limit: int,
    selected_raw_char_limit: int,
    selection_finish_reason: str = "stop",
    selection_transport_truncated: bool | None = None,
) -> dict[str, Any]:
    """Build a restart-safe checkpoint from a model selection without semantic judgment.

    Fold-local evidence IDs are converted to stable protocol digests before
    persistence. The program checks only pairing, identity, scope and resource bounds.
    """

    groups = collect_active_evidence_groups(messages)
    stats = measure_evidence_selection_shadow(groups, selected_ids)
    if not stats.selection_valid:
        raise ValueError("working-state selection contains unknown or duplicate evidence ids")
    human_index = _latest_human_index(messages)
    if human_index is None:
        raise ValueError("working-state checkpoint requires a real human anchor")
    text = str(state_text or "")
    if not text.strip():
        raise ValueError("working-state checkpoint requires non-empty model state")
    if not isinstance(state_char_limit, int) or state_char_limit <= 0:
        raise ValueError("working-state checkpoint requires a positive state_char_limit")
    if not isinstance(selected_raw_char_limit, int) or selected_raw_char_limit <= 0:
        raise ValueError("working-state checkpoint requires a positive selected_raw_char_limit")
    if len(text) > state_char_limit:
        raise ValueError("working-state checkpoint state_text exceeds resource limit")
    if stats.selected_raw_chars > selected_raw_char_limit:
        raise ValueError("working-state selected raw evidence exceeds resource limit")
    finish_reason = str(selection_finish_reason or "")
    finish_reason_key = finish_reason.strip().lower()
    if finish_reason_key in _CHECKPOINT_TRUNCATION_REASONS:
        raise ValueError(
            "working-state selection must finish normally before persistence "
            "(transport truncated)"
        )
    if selection_transport_truncated is not None and not isinstance(
        selection_transport_truncated, bool
    ):
        raise ValueError("working-state selection transport completeness must be boolean")
    if selection_transport_truncated is True:
        raise ValueError(
            "working-state selection must finish normally before persistence "
            "(transport truncated)"
        )
    if selection_transport_truncated is None and finish_reason_key != "stop":
        raise ValueError(
            "working-state selection requires explicit transport completeness "
            "for a non-stop finish reason"
        )
    by_id = {group.descriptor.evidence_id: group for group in groups}
    selected_groups = [by_id[evidence_id] for evidence_id in stats.selected_ids]
    return {
        "version": _WORKING_STATE_CHECKPOINT_VERSION,
        "session_id": str(session_id),
        "provider_id": str(provider_id),
        "model": str(model),
        "human_anchor_index": human_index,
        "human_anchor_digest": _human_anchor_digest(messages[human_index]),
        # S1 only projects state when the Session transcript is still exactly the
        # snapshot on which the model selected evidence. This keeps tail placement
        # chronologically true and leaves later-tail support to S2.
        "boundary_message_count": len(messages),
        "candidate_set_digest": stats.candidate_set_digest,
        "selected_group_digests": [
            group.descriptor.protocol_digest for group in selected_groups
        ],
        "selected_ids": list(stats.selected_ids),
        "state_text": text,
        "state_chars": len(text),
        "state_char_limit": state_char_limit,
        "selected_raw_chars": stats.selected_raw_chars,
        "selected_raw_char_limit": selected_raw_char_limit,
        "selection_finish_reason": finish_reason,
        # Keep exact provider stop reason separate from normalized transport
        # completeness.  A complete tool-call response may end as ``tool_calls``;
        # only a caller with an explicit mechanical transport fact may persist a
        # non-``stop`` checkpoint.
        "selection_transport_truncated": False,
        "selection_complete": True,
    }


def resolve_working_state_checkpoint(
    checkpoint: Any,
    *,
    session_id: str,
    messages: list[Message],
    provider_id: str,
    model: str,
) -> WorkingStateCheckpointResolution:
    """Validate one checkpoint mechanically; stale/malformed state is ineligible."""

    def reject(reason: str) -> WorkingStateCheckpointResolution:
        return WorkingStateCheckpointResolution(eligible=False, reason=reason)

    if not isinstance(checkpoint, dict):
        return reject("missing")
    if checkpoint.get("version") != _WORKING_STATE_CHECKPOINT_VERSION:
        return reject("version")
    if str(checkpoint.get("session_id") or "") != str(session_id):
        return reject("session")
    if str(checkpoint.get("provider_id") or "") != str(provider_id):
        return reject("provider")
    if str(checkpoint.get("model") or "") != str(model):
        return reject("model")
    boundary_raw = checkpoint.get("boundary_message_count")
    if not isinstance(boundary_raw, int | str):
        return reject("boundary_shape")
    try:
        boundary_message_count = int(boundary_raw)
    except ValueError:
        return reject("boundary_shape")
    if boundary_message_count != len(messages):
        return reject("boundary")
    human_index = _latest_human_index(messages)
    human_index_raw = checkpoint.get("human_anchor_index")
    if not isinstance(human_index_raw, int | str):
        return reject("human_anchor_shape")
    try:
        checkpoint_human_index = int(human_index_raw)
    except ValueError:
        return reject("human_anchor_shape")
    if human_index is None or checkpoint_human_index != human_index:
        return reject("human_anchor")
    if str(checkpoint.get("human_anchor_digest") or "") != _human_anchor_digest(messages[human_index]):
        return reject("human_digest")
    groups = collect_active_evidence_groups(messages)
    candidate_digest = evidence_candidate_set_digest(groups)
    if str(checkpoint.get("candidate_set_digest") or "") != candidate_digest:
        return reject("candidate_digest")
    raw_selected = checkpoint.get("selected_group_digests")
    if not isinstance(raw_selected, list) or any(not isinstance(item, str) for item in raw_selected):
        return reject("selected_digest_shape")
    selected = tuple(raw_selected)
    if len(selected) != len(set(selected)):
        return reject("selected_digest_duplicate")
    by_digest = {group.descriptor.protocol_digest: group for group in groups}
    if any(digest not in by_digest for digest in selected):
        return reject("selected_digest_unknown")
    selected_groups = [by_digest[digest] for digest in selected]
    state_text = checkpoint.get("state_text")
    if not isinstance(state_text, str) or not state_text.strip():
        return reject("state_text")
    state_limit_raw = checkpoint.get("state_char_limit")
    selected_limit_raw = checkpoint.get("selected_raw_char_limit")
    if not isinstance(state_limit_raw, int) or state_limit_raw <= 0:
        return reject("state_budget_shape")
    if not isinstance(selected_limit_raw, int) or selected_limit_raw <= 0:
        return reject("selected_budget_shape")
    selected_raw_chars = sum(group.descriptor.raw_chars for group in selected_groups)
    if len(state_text) > state_limit_raw:
        return reject("state_over_budget")
    if selected_raw_chars > selected_limit_raw:
        return reject("selected_over_budget")
    if checkpoint.get("state_chars") != len(state_text):
        return reject("state_size_mismatch")
    if checkpoint.get("selected_raw_chars") != selected_raw_chars:
        return reject("selected_size_mismatch")
    if checkpoint.get("selection_complete") is not True:
        return reject("selection_incomplete")
    finish_reason = str(checkpoint.get("selection_finish_reason") or "")
    finish_reason_key = finish_reason.strip().lower()
    if finish_reason_key in _CHECKPOINT_TRUNCATION_REASONS:
        return reject("selection_finish_reason")
    transport_truncated = checkpoint.get("selection_transport_truncated")
    if transport_truncated is None:
        # v1 checkpoints written before the transport-completeness field are
        # backward compatible only for the historically qualified ``stop`` case.
        if finish_reason_key != "stop":
            return reject("selection_transport_unknown")
    elif not isinstance(transport_truncated, bool):
        return reject("selection_transport_shape")
    elif transport_truncated:
        return reject("selection_transport_truncated")
    return WorkingStateCheckpointResolution(
        eligible=True,
        reason="eligible",
        state_text=state_text,
        preserve_group_digests=selected,
        candidate_set_digest=candidate_digest,
        selected_raw_chars=selected_raw_chars,
    )


def measure_evidence_selection_shadow(
    groups: tuple[AtomicEvidenceGroup, ...], selected_ids: list[str] | tuple[str, ...]
) -> EvidenceSelectionShadowStats:
    """Measure an external/model selection without applying it to provider history."""

    selected = tuple(str(item) for item in selected_ids)
    by_id = {group.descriptor.evidence_id: group for group in groups}
    seen: set[str] = set()
    duplicate_count = 0
    known_unique: list[AtomicEvidenceGroup] = []
    unknown_count = 0
    for evidence_id in selected:
        if evidence_id in seen:
            duplicate_count += 1
            continue
        seen.add(evidence_id)
        group = by_id.get(evidence_id)
        if group is None:
            unknown_count += 1
            continue
        known_unique.append(group)
    return EvidenceSelectionShadowStats(
        candidate_set_digest=evidence_candidate_set_digest(groups),
        selected_ids=selected,
        candidate_group_count=len(groups),
        candidate_raw_chars=sum(group.descriptor.raw_chars for group in groups),
        selected_group_count=len(known_unique),
        selected_raw_chars=sum(group.descriptor.raw_chars for group in known_unique),
        selected_tool_call_count=sum(len(group.descriptor.tool_call_ids) for group in known_unique),
        unknown_id_count=unknown_count,
        duplicate_id_count=duplicate_count,
        pairing_valid=True,
        selection_valid=unknown_count == 0 and duplicate_count == 0,
    )


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
    *,
    preserve_group_digests: tuple[str, ...] | list[str] | set[str] | frozenset[str] = (),
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
    projected = list(messages)
    preserve_requested = {str(item) for item in preserve_group_digests if str(item)}
    preserved_starts: set[int] = set()
    if preserve_requested:
        # Digesting raw evidence is intentionally paid only on the S1 checkpoint
        # path; the default receipt projection keeps the S0 lightweight span path.
        evidence_groups = collect_active_evidence_groups(messages)
        available = {group.descriptor.protocol_digest for group in evidence_groups}
        # Never partially apply a malformed/stale preserve set. The normal receipt
        # path is the truthful fail-open representation if any requested digest is
        # absent; ingress normally prevents this before the projector is called.
        if preserve_requested.issubset(available):
            preserved_starts = {
                group.start
                for group in evidence_groups
                if group.descriptor.protocol_digest in preserve_requested
            }
    pending: list[tuple[int, Message]] = []
    pending_chars = 0
    pending_group_count = 0
    grace_queue: list[tuple[list[tuple[int, Message]], int]] = []
    folded_results = 0
    folded_groups = 0
    receipt_chars = 0
    fold_boundaries: list[int] = []
    latest_raw_chars = 0
    for group in _collect_active_tool_group_spans(messages):
        group_raw_chars = sum(len(messages[idx].content or "") for idx in group.result_indices)
        if group.start in preserved_starts:
            # Model-selected direct evidence remains the exact original
            # assistant(tool_calls)+tool group. No program summary is substituted.
            continue
        if not group.exposed:
            latest_raw_chars += group_raw_chars
        else:
            group_receipts: list[tuple[int, Message]] = []
            group_chars = 0
            for idx in group.result_indices:
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
                    fold_boundaries.append(group.end_exclusive)
                    pending = []
                    pending_chars = 0
                    pending_group_count = 0
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


def _human_ingress_wire_identity(message: Message) -> str | None:
    """Return exact provider-payload identity for one genuine human ingress.

    User text alone is not sufficient because two visually identical messages may
    carry different attachment facts.  ``to_llm_dict`` is the canonical mechanical
    provider representation and contains no task interpretation.
    """
    if not is_human_user_message(message):
        return None
    try:
        wire = message.to_llm_dict()
        payload = json.dumps(
            wire, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except Exception:  # noqa: BLE001 — identity failure must preserve visibility
        return None
    return hashlib.sha256(payload).hexdigest()


def superseded_human_attempt_spans(
    messages: list[Message],
) -> tuple[tuple[int, int], ...]:
    """Find older exact-human attempts superseded by a later resolved duplicate.

    This is a lifecycle/identity rule, not semantic task completion:
    - both ingresses must be genuine human messages with byte-equivalent provider
      payloads (including attachment projection);
    - only a *later* ingress already carrying a durable resolved-episode ref can
      supersede an older unresolved duplicate;
    - the whole older human-turn span is retired from provider view so its partial
      assistant/tool trajectory cannot survive as a ghost task;
    - storage/EventLog bytes and metadata remain untouched.

    Non-identical or still-unresolved human turns fail open and remain visible.
    """
    if not messages:
        return ()
    human_indices = [
        idx for idx, message in enumerate(messages) if is_human_user_message(message)
    ]
    if len(human_indices) < 2:
        return ()

    resolved_later_identities: set[str] = set()
    spans_rev: list[tuple[int, int]] = []
    for pos in range(len(human_indices) - 1, -1, -1):
        start = human_indices[pos]
        message = messages[start]
        identity = _human_ingress_wire_identity(message)
        if identity is None:
            continue
        if is_resolved_episode_message(message):
            resolved_later_identities.add(identity)
            continue
        if identity not in resolved_later_identities:
            continue
        end = human_indices[pos + 1] if pos + 1 < len(human_indices) else len(messages)
        spans_rev.append((start, end))
    spans_rev.reverse()
    return tuple(spans_rev)


def provider_view_without_resolved_episodes(messages: list[Message]) -> list[Message]:
    """Project working context after durable lifecycle retirement.

    The historical public name is kept for compatibility. Besides whole resolved
    episodes and consumed/closed tool spans, exact older human attempts are also
    retired when a later byte-equivalent human ingress has durably resolved. This
    prevents failed/restarted duplicate user turns from surviving as executable
    ghost tasks. Storage/event truth is never mutated.
    """

    superseded_indices: set[int] = set()
    for start, end in superseded_human_attempt_spans(messages):
        superseded_indices.update(range(start, end))
    return [
        message
        for idx, message in enumerate(messages)
        if idx not in superseded_indices and provider_message_visible(message)
    ]


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


def backfill_completed_delegated_spans(store: EpisodeStore | None, session: Any) -> list[str]:
    """Durably retire completed delegated runs from later human provider views.

    Delegated user-shaped ingress is intentionally excluded from genuine-human
    episode lifecycle. Without a parallel closed lifecycle, a completed scheduled
    run can survive forever while newer resolved human episodes retire around it.
    Selection is mechanical only: delegated provenance plus a completed model
    terminal before the next user-shaped ingress.
    """

    if store is None:
        return []
    messages: list[Message] = list(getattr(session, "messages", []) or [])
    session_id = str(getattr(session, "session_id", "") or "")
    refs: list[str] = []
    starts = [
        idx
        for idx, message in enumerate(messages)
        if message.role == "user" and _metadata(message).get("ingress_delegated") is True
    ]
    for start in starts:
        existing = delegated_span_ref(messages[start])
        if existing and is_closed_delegated_span_message(messages[start]):
            refs.append(existing)
            continue
        end = next(
            (
                idx
                for idx in range(start + 1, len(messages))
                if messages[idx].role == "user"
                and (
                    is_human_user_message(messages[idx])
                    or _metadata(messages[idx]).get("ingress_delegated") is True
                )
            ),
            len(messages),
        )
        terminal = next(
            (
                idx
                for idx in range(end - 1, start, -1)
                if _completed_model_answer(messages[idx])
            ),
            None,
        )
        if terminal is None:
            continue
        ref = stable_delegated_span_ref(session_id, messages[start], start)
        try:
            store.index_delegated_span(
                session_id,
                ref=ref,
                user_seq=start,
                terminal_seq=terminal,
                raw_messages=messages[start : terminal + 1],
            )
        except Exception:  # noqa: BLE001 - durable failure means keep provider-visible
            logger.warning(
                "delegated span 索引失败（保留 provider 可见）: sid=%s start=%d terminal=%d",
                session_id,
                start,
                terminal,
                exc_info=True,
            )
            continue
        for idx in range(start, terminal + 1):
            md = dict(_metadata(messages[idx]))
            md[DELEGATED_SPAN_REF_KEY] = ref
            md[DELEGATED_SPAN_STATE_KEY] = DELEGATED_SPAN_STATE
            messages[idx].metadata = md
        refs.append(ref)
    return refs


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
