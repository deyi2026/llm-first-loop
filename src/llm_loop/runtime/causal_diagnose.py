"""Read-only mechanical diagnosis over EventStore causality facts.

This module compares recorded request construction/runtime facts.  It deliberately
reports divergence, constraint hits and unknowns; it never decides semantic answer
quality or changes runtime behavior.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

_COMPONENTS = {
    "runtime": "runtime.causality/runtime snapshot",
    "generation_contract": "llm client/provider contract",
    "input_budget": "routing/input-output capacity contract",
    "ingress": "core.prompt_build.stages.ingress_resolution",
    "history": "core.prompt_build.stages.history_pipeline",
    "recent_continuity": "core.recent_continuity",
    "tool_surface": "tools.registry/provider projection",
    "wire_transform": "provider retry/fallback wire transform",
    "cache": "provider/cache usage observation",
}


@dataclass(frozen=True, slots=True)
class _Attempt:
    seq: int
    event_type: str
    payload: dict[str, Any]
    usage: dict[str, Any] | None = None
    interruption: dict[str, Any] | None = None


def _event_parts(event: Any) -> tuple[int, str, dict[str, Any]]:
    return (
        int(getattr(event, "seq", 0) or 0),
        str(getattr(event, "type", "") or ""),
        dict(getattr(event, "payload", None) or {}),
    )


def _attempts(events: Iterable[Any]) -> list[_Attempt]:
    rows = [_event_parts(event) for event in events]
    request_rows = [row for row in rows if row[1] in {"request.meta", "request.attempt"}]
    out: list[_Attempt] = []
    for index, (seq, event_type, payload) in enumerate(request_rows):
        next_seq = request_rows[index + 1][0] if index + 1 < len(request_rows) else 2**63 - 1
        usage = next(
            (
                p
                for s, t, p in rows
                if seq < s < next_seq and t == "request.usage"
            ),
            None,
        )
        interruption = next(
            (
                p
                for s, t, p in rows
                if seq < s < next_seq and t == "llm.interrupted"
            ),
            None,
        )
        out.append(
            _Attempt(
                seq=seq,
                event_type=event_type,
                payload=payload,
                usage=usage,
                interruption=interruption,
            )
        )
    return out


def _ingress_volume(payload: dict[str, Any]) -> dict[str, Any]:
    """Return raw ingress volumes for observation, never for divergence ranking."""
    influence = payload.get("influence") or {}
    ingress = influence.get("ingress") or {}
    storage = int(ingress.get("storage_messages", 0) or 0)
    trace = int(ingress.get("trace_messages", storage) or 0)
    eligible = int(ingress.get("eligible_messages", trace) or 0)
    provider = int(ingress.get("provider_base_messages", eligible) or 0)
    working = ingress.get("tool_working_set") or {}
    return {
        "storage_messages": storage,
        "trace_messages": trace,
        "eligible_messages": eligible,
        "provider_base_messages": provider,
        "trace_removed": max(0, storage - trace),
        "eligibility_removed": max(0, trace - eligible),
        "provider_scrub_removed": max(0, eligible - provider),
        "stale_cleanup": dict(ingress.get("stale_cleanup") or {}),
        "working_state_selected_raw_chars": int(
            ingress.get("working_state_selected_raw_chars", 0) or 0
        ),
        "folded_results": int(working.get("folded_results", 0) or 0),
        "folded_groups": int(working.get("folded_groups", 0) or 0),
    }


def _normalized_ingress(payload: dict[str, Any]) -> dict[str, Any]:
    """Compare ingress mechanism state, not naturally growing session volume."""
    influence = payload.get("influence") or {}
    ingress = influence.get("ingress") or {}
    working = ingress.get("tool_working_set") or {}
    volume = _ingress_volume(payload)
    return {
        "trace_filter_active": volume["trace_removed"] > 0,
        "eligibility_filter_active": volume["eligibility_removed"] > 0,
        "provider_scrub_active": volume["provider_scrub_removed"] > 0,
        "stale_cleanup_active": {
            str(name): bool(value)
            for name, value in sorted((ingress.get("stale_cleanup") or {}).items())
        },
        "working_state_reason": str(ingress.get("working_state_reason") or ""),
        "working_state_present": volume["working_state_selected_raw_chars"] > 0,
        "tool_working_set": {
            "enabled": bool(working.get("enabled")),
            "folded_results_active": volume["folded_results"] > 0,
            "folded_groups_active": volume["folded_groups"] > 0,
        },
    }


def _normalized_history(payload: dict[str, Any]) -> dict[str, Any]:
    history = (payload.get("influence") or {}).get("history") or {}
    stats = history.get("compaction_stats") or {}
    return {
        "effective_budget": int(history.get("effective_budget", payload.get("budget", 0)) or 0),
        "compacted": bool(history.get("compacted")),
        "anchor_moved": bool(history.get("anchor_moved")),
        "reopened_marker_count": int(history.get("reopened_marker_count", 0) or 0),
        "cache_boundary_mode": str(stats.get("cache_boundary_mode") or "inactive"),
    }


def _normalized_input_budget(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("input_budget") or {}
    return {
        "requested_input_tokens": value.get("requested_input_tokens"),
        "allowed_input_tokens": value.get("allowed_input_tokens"),
        "tool_schema_reserve_chars": int(value.get("tool_schema_reserve_chars", 0) or 0),
        "effective_history_budget_chars": int(
            value.get("effective_history_budget_chars", payload.get("budget", 0)) or 0
        ),
        "limited_by": str(value.get("limited_by") or ""),
    }


def _normalized_continuity(payload: dict[str, Any]) -> dict[str, Any]:
    value = (payload.get("influence") or {}).get("recent_continuity") or {}
    return {
        "applied": bool(value.get("applied")),
        "source": str(value.get("source") or value.get("reason") or ""),
        "dialogue_pairs": int(value.get("dialogue_pairs", 0) or 0),
        "rehydrated": bool(value.get("rehydrated")),
        "runtime_fact": bool(value.get("runtime_fact")),
    }



def _normalized_wire_transform(payload: dict[str, Any]) -> dict[str, Any]:
    transform = payload.get("transform") or {}
    return {
        "wire_shape_changed": bool(transform.get("wire_shape_changed")),
        "messages_before": int(transform.get("messages_before", 0) or 0),
        "messages_after": int(transform.get("messages_after", 0) or 0),
        "tail_users_merged": int(transform.get("tail_users_merged", 0) or 0),
    }


def _normalized_cache(attempt: _Attempt) -> dict[str, Any] | None:
    usage = attempt.usage
    if usage is None:
        return None
    return {
        "stable_prefix_fp": str(usage.get("stable_prefix_fp") or ""),
        "prefix_changed": bool(usage.get("prefix_changed")),
        "prefix_change_reason": str(usage.get("prefix_change_reason") or ""),
        "cache_prefix_epoch": int(usage.get("cache_prefix_epoch", 0) or 0),
        "compaction_epoch": int(usage.get("compaction_epoch", 0) or 0),
    }

def _stage_values(attempt: _Attempt) -> list[tuple[str, Any]]:
    payload = attempt.payload
    runtime = payload.get("runtime_snapshot") or {}
    values: list[tuple[str, Any]] = []
    if runtime.get("snapshot_id"):
        values.append(("runtime", str(runtime.get("snapshot_id") or "")))
    values.append(("generation_contract", dict(payload.get("generation_contract") or {})))
    if payload.get("input_budget"):
        values.append(("input_budget", _normalized_input_budget(payload)))
    if payload.get("influence"):
        values.extend(
            [
                ("ingress", _normalized_ingress(payload)),
                ("history", _normalized_history(payload)),
                ("recent_continuity", _normalized_continuity(payload)),
            ]
        )
    values.append(
        (
            "tool_surface",
            {"tools_count": int(payload.get("tools_count", 0) or 0)},
        )
    )
    if attempt.event_type == "request.attempt":
        values.append(("wire_transform", _normalized_wire_transform(payload)))
    cache = _normalized_cache(attempt)
    if cache is not None:
        values.append(("cache", cache))
    return values


def _attempt_card(attempt: _Attempt) -> dict[str, Any]:
    payload = attempt.payload
    runtime = payload.get("runtime_snapshot") or {}
    return {
        "seq": attempt.seq,
        "attempt_id": str(payload.get("attempt_id") or ""),
        "attempt_kind": str(payload.get("attempt_kind") or "primary"),
        "attempt_index": int(payload.get("attempt_index", 0) or 0),
        "round": int(payload.get("round", 0) or 0),
        "model": str(payload.get("model") or (payload.get("generation_contract") or {}).get("model") or ""),
        "provider": str((payload.get("generation_contract") or {}).get("provider") or payload.get("provider") or ""),
        "runtime_snapshot_id": str(runtime.get("snapshot_id") or ""),
        "history_chars": int(payload.get("history_chars", 0) or 0),
        "reasoning_chars": int(payload.get("reasoning_chars", 0) or 0),
        "provider_visible_chars": int(payload.get("provider_visible_chars", 0) or 0),
        "provider_structure_fp": str(payload.get("provider_structure_fp") or ""),
        "usage_available": attempt.usage is not None,
        "interruption_available": attempt.interruption is not None,
        "ingress_volume": _ingress_volume(payload) if payload.get("influence") else None,
    }


def _select_target(attempts: list[_Attempt], target_attempt_id: str = "") -> _Attempt | None:
    if target_attempt_id:
        return next(
            (a for a in attempts if str(a.payload.get("attempt_id") or "") == target_attempt_id),
            None,
        )
    return attempts[-1] if attempts else None


def _select_reference(attempts: list[_Attempt], target: _Attempt) -> tuple[_Attempt | None, str]:
    prior = [a for a in attempts if a.seq < target.seq]
    if target.event_type == "request.attempt":
        target_round = int(target.payload.get("round", 0) or 0)
        for candidate in reversed(prior):
            if int(candidate.payload.get("round", 0) or 0) == target_round:
                return candidate, "preceding_attempt_same_round"
    target_model = str(target.payload.get("model") or "")
    target_provider = str((target.payload.get("generation_contract") or {}).get("provider") or "")
    for candidate in reversed(prior):
        candidate_provider = str(
            (candidate.payload.get("generation_contract") or {}).get("provider") or ""
        )
        if (
            candidate.usage is not None
            and str(candidate.payload.get("model") or "") == target_model
            and candidate_provider == target_provider
        ):
            return candidate, "previous_provider_success_same_model_provider"
    for candidate in reversed(prior):
        if candidate.usage is not None:
            return candidate, "previous_provider_success"
    return (prior[-1], "previous_recorded_attempt") if prior else (None, "none")


def _constraint_hits(target: _Attempt) -> list[dict[str, Any]]:
    payload = target.payload
    generation = payload.get("generation_contract") or {}
    usage = target.usage or {}
    interrupted = target.interruption or {}
    hits: list[dict[str, Any]] = []
    max_tokens = generation.get("max_tokens")
    tokens_out = usage.get("tokens_out")
    token_source = "request.usage"
    if not isinstance(tokens_out, int):
        tokens_out = interrupted.get("completion_tokens")
        token_source = "llm.interrupted"
    if (
        isinstance(max_tokens, int)
        and max_tokens > 0
        and isinstance(tokens_out, int)
        and tokens_out >= max_tokens
    ):
        hit: dict[str, Any] = {
            "constraint": "output_budget",
            "observed": tokens_out,
            "limit": max_tokens,
            "mechanical_fact": "provider output tokens reached configured max_tokens",
        }
        if token_source == "llm.interrupted":
            hit["evidence_source"] = token_source
            if (
                int(interrupted.get("reasoning_tail_chars", 0) or 0) > 0
                and int(interrupted.get("text_tail_chars", 0) or 0) == 0
                and int(interrupted.get("tool_call_draft_count", 0) or 0) == 0
            ):
                hit["terminal_shape"] = "reasoning_only_no_visible_text_or_tool_draft"
        hits.append(hit)
    headroom = usage.get("context_headroom_tokens")
    if isinstance(headroom, int) and headroom <= 0:
        hits.append(
            {
                "constraint": "context_headroom",
                "observed": headroom,
                "mechanical_fact": "recorded context headroom is non-positive",
            }
        )
    return hits



def _target_unknowns(target: _Attempt, target_card: dict[str, Any]) -> list[str]:
    unknown: list[str] = []
    if not target_card["runtime_snapshot_id"] and target.event_type == "request.meta":
        unknown.append("target runtime snapshot unavailable")
    if target.usage is None:
        unknown.append("target request.usage unavailable; cache constraints unknown")
        if not isinstance((target.interruption or {}).get("completion_tokens"), int):
            unknown.append("provider completion constraint unknown")
    if target.event_type == "request.attempt" and not target.payload.get("influence"):
        unknown.append("exceptional attempt reuses/rebuilds prior projection; full stage influence not recorded")
    return unknown

def diagnose_causality(events: Iterable[Any], *, target_attempt_id: str = "") -> dict[str, Any]:
    """Return a bounded mechanical comparison; never mutate runtime or infer answer quality."""
    attempts = _attempts(events)
    target = _select_target(attempts, target_attempt_id)
    if target is None:
        return {
            "status": "insufficient_evidence",
            "observed_facts": {"recorded_attempts": 0},
            "earliest_mechanical_divergence": None,
            "constraint_hits": [],
            "unchanged_facts": [],
            "unknown": ["no request.meta/request.attempt events found"],
        }
    reference, reference_basis = _select_reference(attempts, target)
    target_card = _attempt_card(target)
    observed = {
        "recorded_attempts": len(attempts),
        "target": target_card,
        "reference_basis": reference_basis,
        "reference": _attempt_card(reference) if reference else None,
    }
    if reference is None:
        return {
            "status": "single_attempt",
            "observed_facts": observed,
            "earliest_mechanical_divergence": None,
            "constraint_hits": _constraint_hits(target),
            "unchanged_facts": [],
            "unknown": [
                "no earlier recorded attempt is available for mechanical comparison",
                *_target_unknowns(target, target_card),
            ],
        }

    ref_stages = dict(_stage_values(reference))
    target_stages = _stage_values(target)
    unchanged: list[str] = []
    divergence: dict[str, Any] | None = None
    for stage, target_value in target_stages:
        if stage == "cache" and "cache" not in ref_stages:
            continue
        if stage == "wire_transform" and "wire_transform" not in ref_stages:
            reference_value = {
                "wire_shape_changed": False,
                "messages_before": 0,
                "messages_after": 0,
                "tail_users_merged": 0,
            }
        else:
            reference_value = ref_stages.get(stage)
        if target_value == reference_value:
            unchanged.append(stage)
            continue
        if divergence is None:
            divergence = {
                "stage": stage,
                "component": _COMPONENTS[stage],
                "reference": reference_value,
                "target": target_value,
                "note": "mechanical difference only; this is not a semantic root-cause judgment",
            }

    unknown = _target_unknowns(target, target_card)
    return {
        "status": "compared",
        "observed_facts": observed,
        "earliest_mechanical_divergence": divergence,
        "constraint_hits": _constraint_hits(target),
        "unchanged_facts": unchanged,
        "unknown": unknown,
    }


def diagnose_event_store(store: Any, session_id: str, *, target_attempt_id: str = "") -> dict[str, Any]:
    if not session_id:
        return {
            "status": "session_required",
            "observed_facts": {},
            "earliest_mechanical_divergence": None,
            "constraint_hits": [],
            "unchanged_facts": [],
            "unknown": ["current session id unavailable"],
        }
    try:
        events = store.read(session_id)
    except Exception as exc:  # noqa: BLE001 - read-only diagnostics fail honestly
        return {
            "status": "read_failed",
            "observed_facts": {},
            "earliest_mechanical_divergence": None,
            "constraint_hits": [],
            "unchanged_facts": [],
            "unknown": [f"event store read failed: {type(exc).__name__}"],
        }
    return diagnose_causality(events, target_attempt_id=target_attempt_id)
