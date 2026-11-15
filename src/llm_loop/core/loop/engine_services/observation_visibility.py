"""Mechanical pre-send check for the latest completed tool observation.

This initial batch proves only an exact, paired raw exchange in the provider
view. It deliberately does not treat durable storage, arbitrary evidence://
text, repeat hints or a matching tool-call ID as proof of model visibility.
A validated owner-scoped exact-ref projection is a separate gated capability;
until it exists, missing raw observations must HOLD before Provider send.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Mapping
from typing import Any


def _field(message: Any, name: str) -> Any:
    return message.get(name) if isinstance(message, dict) else getattr(message, name, None)


def _role(message: Any) -> str:
    return str(_field(message, "role") or "")


def _call_signature(call: Any) -> tuple[str, str, str]:
    if isinstance(call, dict):
        fn = call.get("function") or call
        call_id = call.get("id")
        name = fn.get("name") if isinstance(fn, dict) else ""
        args = fn.get("arguments") if isinstance(fn, dict) else None
    else:
        call_id = getattr(call, "id", None)
        name = getattr(call, "name", "")
        args = getattr(call, "arguments", None)
    if isinstance(args, str):
        with contextlib.suppress(ValueError, TypeError):
            args = json.loads(args)
    encoded = json.dumps(
        args, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return str(call_id or ""), str(name or ""), encoded


def _calls(message: Any) -> tuple[tuple[str, str, str], ...]:
    return tuple(_call_signature(call) for call in (_field(message, "tool_calls") or ()))


def latest_completed_tool_group(messages: list[Any], after_ref: int | None) -> dict | None:
    """Return latest same-run group and its *exact* persisted observations.

    None means no assistant tool call after the known current-run ingress. An
    incomplete/ambiguous group is returned as invalid, never treated as absent.
    Unknown ingress identity must not scan and confuse earlier Runs.
    """
    if not isinstance(after_ref, int) or not 0 <= after_ref < len(messages):
        return None
    latest: dict | None = None
    for index in range(after_ref + 1, len(messages)):
        assistant = messages[index]
        if _role(assistant) != "assistant":
            continue
        calls = _calls(assistant)
        if not calls:
            continue
        ids = [call[0] for call in calls]
        latest = {"index": index, "call_ids": ids, "valid": False}
        if not all(ids) or len(ids) != len(set(ids)):
            continue
        receipts: dict[str, str] = {}
        j = index + 1
        while j < len(messages) and _role(messages[j]) == "tool":
            tool_id = str(_field(messages[j], "tool_call_id") or "")
            if not tool_id or tool_id not in ids or tool_id in receipts:
                break
            receipts[tool_id] = str(_field(messages[j], "content") or "")
            j += 1
        if set(receipts) == set(ids) and all(receipts.values()):
            latest = {
                "index": index,
                "call_ids": ids,
                "calls": calls,
                "receipts": receipts,
                "valid": True,
            }
    return latest


def group_visible_in_provider_view(
    group: dict | None,
    provider_messages: list[dict],
    *,
    active_ingress_ref: str = "",
) -> bool:
    """Compare exact source call arguments and tool contents after active ingress.

    A same-ID but altered/truncated/placeholder result is NOT raw visibility.
    An unverified ref string is NOT raw visibility. All tool receipts must be
    consecutive and protocol-paired, with no duplicates or foreign IDs.
    """
    if group is None:
        return True
    if not group.get("valid"):
        return False
    start = 0
    if active_ingress_ref:
        for i, message in enumerate(provider_messages):
            if str(message.get("_active_run_ingress_ref") or "") == active_ingress_ref:
                start = i + 1
                break
        else:
            return False
    expected_calls = group["calls"]
    expected_receipts = group["receipts"]
    for i in range(start, len(provider_messages)):
        assistant = provider_messages[i]
        if _role(assistant) != "assistant" or _calls(assistant) != expected_calls:
            continue
        segment = provider_messages[i + 1 : i + 1 + len(expected_receipts)]
        if len(segment) != len(expected_receipts):
            continue
        observed: dict[str, str] = {}
        for tool in segment:
            if _role(tool) != "tool":
                break
            tool_id = str(_field(tool, "tool_call_id") or "")
            content = str(_field(tool, "content") or "")
            if tool_id not in expected_receipts or tool_id in observed:
                break
            observed[tool_id] = content
        if observed == expected_receipts:
            return True
    return False


def _restore_latest_raw_group(
    group: dict,
    provider_messages: list[dict],
    *,
    active_ingress_ref: str,
) -> list[dict] | None:
    """Replace only a paired latest first-view with exact durable Session bytes.

    The current provider projection may have bounded an otherwise recoverable
    tool result to 8192 characters. That representation limit is not a physical
    model-window limit. Never restore on missing ingress, changed arguments,
    incomplete/duplicate receipts, or ambiguous matching groups.
    """
    if not group.get("valid") or not active_ingress_ref:
        return None
    ingress_positions = [
        i
        for i, row in enumerate(provider_messages)
        if str(row.get("_active_run_ingress_ref") or "") == active_ingress_ref
    ]
    if len(ingress_positions) != 1:
        return None
    expected_receipts = group["receipts"]
    matched: list[int] = []
    for i in range(ingress_positions[0] + 1, len(provider_messages)):
        if (
            _role(provider_messages[i]) != "assistant"
            or _calls(provider_messages[i]) != group["calls"]
        ):
            continue
        segment = provider_messages[i + 1 : i + 1 + len(expected_receipts)]
        if len(segment) != len(expected_receipts) or any(_role(row) != "tool" for row in segment):
            continue
        ids = [str(row.get("tool_call_id") or "") for row in segment]
        if len(ids) != len(set(ids)) or set(ids) != set(expected_receipts):
            continue
        if (
            i + 1 + len(segment) < len(provider_messages)
            and _role(provider_messages[i + 1 + len(segment)]) == "tool"
        ):
            continue
        if any(
            _role(row) == "assistant" and _calls(row)
            for row in provider_messages[i + 1 + len(segment) :]
        ):
            continue
        matched.append(i)
    if len(matched) != 1:
        return None
    candidate = [dict(row) for row in provider_messages]
    for row in candidate[matched[0] + 1 : matched[0] + 1 + len(expected_receipts)]:
        row["content"] = expected_receipts[str(row["tool_call_id"])]
    if not group_visible_in_provider_view(group, candidate, active_ingress_ref=active_ingress_ref):
        return None
    return candidate


def ensure_latest_observation_visible(
    engine: Any,
    sess: Any,
    messages: list[dict],
    *,
    session_id: str,
    active_turn_ref: int | None,
    active_ingress_ref: str,
    effective_budget: int,
    budget_info: dict,
    request_preflight: Any,
    tools_param: list[dict],
    chat_model_arg: str | None,
    model: str | None,
    planned_label: str,
    rounds: int,
) -> tuple[list[dict], str]:
    """Return (provider messages, HOLD reason); empty reason means safe to proceed.

    Reuse the existing side-effect-free conservative Session projection, never
    replay tools or invent a ref. A physical window budget constrains the raw
    rebuild; a soft history cap alone is not proof of physical non-fit.
    """
    try:
        from llm_loop.core.message import dict_wire_chars
        group = latest_completed_tool_group(sess.messages, active_turn_ref)
        physical_limit = (budget_info or {}).get("limited_by") in (
            "model_window",
            "input_token_budget",
        )
        if group is None:
            return messages, ""
        # No raw arguments/content/refs in diagnostics. At most two candidate
        # stages are inspected; this makes the next HOLD attributable without
        # weakening the existing fail-closed visibility invariant.
        stage_facts: list[dict[str, Any]] = []
        if group.get("valid"):
            raw_visible = group_visible_in_provider_view(
                group, messages, active_ingress_ref=active_ingress_ref
            )
            first = (
                messages
                if raw_visible
                else _restore_latest_raw_group(
                    group, messages, active_ingress_ref=active_ingress_ref
                )
            )
            # Current view first, then a read-only Session rebuild; never replay tools.
            for stage in ("current", "rebuilt"):
                stage_fact: dict[str, Any] = {"stage": stage}
                if stage == "current":
                    candidate = first
                else:
                    rebuilt = engine._build_conservative_active_run_messages(
                        sess,
                        max_chars=effective_budget,
                        model=model,
                        planned_label=planned_label,
                        logical_round=rounds,
                    )
                    stage_fact["rebuild_state"] = rebuilt.state
                    stage_fact["retired_groups"] = getattr(rebuilt, "retired_groups", None)
                    stage_fact["rebuild_chars"] = getattr(rebuilt, "projected_chars", None)
                    candidate = list(rebuilt.messages) if rebuilt.state == "rebuilt" else None
                    if candidate is not None and not group_visible_in_provider_view(
                        group, candidate, active_ingress_ref=active_ingress_ref
                    ):
                        candidate = _restore_latest_raw_group(
                            group, candidate, active_ingress_ref=active_ingress_ref
                        )
                if candidate is None or not group_visible_in_provider_view(
                    group, candidate, active_ingress_ref=active_ingress_ref
                ):
                    stage_fact["rejection"] = "raw_not_visible"
                    stage_facts.append(stage_fact)
                    continue
                projected_chars = sum(dict_wire_chars(row) for row in candidate)
                stage_fact["projected_chars"] = projected_chars
                raw_fits = not physical_limit or projected_chars <= effective_budget
                if not raw_fits:
                    stage_fact["rejection"] = "raw_over_budget"
                if raw_fits and callable(request_preflight):
                    preflight = request_preflight(candidate, tools_param, model=chat_model_arg)
                    raw_fits = isinstance(preflight, Mapping) and not bool(
                        preflight.get("hard_overflow", False)
                    )
                    if not raw_fits:
                        stage_fact["rejection"] = (
                            "preflight_overflow"
                            if isinstance(preflight, Mapping) and preflight.get("hard_overflow")
                            else "preflight_invalid"
                        )
                if raw_fits:
                    if stage == "rebuilt" or not raw_visible:
                        engine._event_append(
                            session_id,
                            "request.observation_visibility",
                            {
                                "round": rounds,
                                "action": (
                                    "raw_group_rebuilt_from_current_session"
                                    if stage == "rebuilt"
                                    else "raw_group_restored_from_session"
                                ),
                                "group_index": group["index"],
                                "projected_chars": projected_chars,
                                "budget_chars": effective_budget,
                            },
                        )
                    return candidate, ""
                # Exact-ref still requires owner, version, hydration, schema and preflight.
                exact_ref = _qualified_exact_ref_projection(
                    engine,
                    sess,
                    group,
                    candidate,
                    session_id=session_id,
                    active_ingress_ref=active_ingress_ref,
                    tools_param=tools_param,
                    effective_budget=effective_budget,
                    physical_limit=physical_limit,
                    request_preflight=request_preflight,
                    chat_model_arg=chat_model_arg,
                )
                if exact_ref is not None:
                    ref_messages, projected_chars = exact_ref
                    engine._event_append(
                        session_id,
                        "request.observation_visibility",
                        {
                            "round": rounds,
                            "action": "exact_ref_projected",
                            "group_index": group["index"],
                            "ref_count": len(group["call_ids"]),
                            "projected_chars": projected_chars,
                            "budget_chars": effective_budget,
                        },
                    )
                    return ref_messages, ""
                stage_fact["exact_ref_qualified"] = False
                stage_facts.append(stage_fact)
        engine._event_append(
            session_id,
            "request.observation_visibility",
            {
                "round": rounds,
                "group_index": group["index"] if group else None,
                "call_ids": (group or {}).get("call_ids", []),
                "visible": False,
                "action": "provider_send_blocked",
                "reason": "context_capacity_unavailable",
                "latest_group_valid": bool(group.get("valid")),
                "active_ingress_present": bool(active_ingress_ref),
                "raw_visible_in_current": (
                    bool(raw_visible) if group.get("valid") else False
                ),
                "physical_limit": physical_limit,
                "limited_by": (budget_info or {}).get("limited_by"),
                "budget_chars": effective_budget,
                "stage_checks": stage_facts,
            },
        )
        engine._record_action(
            "action.llm_decide",
            "observation_visibility_hold",
            "latest_tool_group_not_in_provider_view;provider_sent=false;run_incomplete",
        )
        return messages, "context_capacity_unavailable"
    except Exception:
        # The gate itself is a safety boundary. No fail-open or fake success.
        import logging

        logging.getLogger(__name__).exception("observation visibility guard failed")
        return messages, "observation_guard_fault"


def _qualified_exact_ref_projection(
    engine: Any,
    sess: Any,
    group: dict,
    raw_messages: list[dict],
    *,
    session_id: str,
    active_ingress_ref: str,
    tools_param: list[dict],
    effective_budget: int,
    physical_limit: bool,
    request_preflight: Any,
    chat_model_arg: str | None,
) -> tuple[list[dict], int] | None:
    """Owner-authorized, bounded, protocol-paired historical EvidenceRef capsule.

    This does not execute the source tool. Only a registered EvidenceReadTool
    and a provider-callable read_evidence schema can qualify an existing ref.
    """
    from llm_loop.core.message import dict_wire_chars
    from llm_loop.memory.evidence import (
        AvailabilityState,
        EvidenceError,
        EvidenceRef,
        FreshnessState,
        OwnerScope,
        RangeType,
        SourceKind,
        SourceVersionPolicy,
    )
    from llm_loop.tools.evidence_tools import EvidenceReadTool

    if not any(
        isinstance(row, dict)
        and isinstance(row.get("function"), dict)
        and row["function"].get("name") == "read_evidence"
        for row in tools_param
    ):
        return None
    try:
        tool = engine.registry.get("read_evidence")
        if not isinstance(tool, EvidenceReadTool):
            return None
        owner = tool.owner_resolver()
        if not isinstance(owner, OwnerScope) or owner.session_id != session_id:
            return None
        ids = group["call_ids"]
        index = group["index"]
        source_tools = sess.messages[index + 1 : index + 1 + len(ids)]
        if len(source_tools) != len(ids):
            return None
        capsules: dict[str, str] = {}
        for message in source_tools:
            tool_id = str(_field(message, "tool_call_id") or "")
            metadata = _field(message, "metadata") or {}
            if (
                tool_id not in ids
                or tool_id in capsules
                or not isinstance(metadata, dict)
                or metadata.get("recoverability_status") != "recorded"
            ):
                return None
            ref = EvidenceRef(str(metadata.get("evidence_ref") or ""))
            record = tool.ledger.require_authorized(owner, ref)
            if record.tool_call_id != tool_id:
                return None
            source_tool_name = str(_field(message, "tool_name") or "")
            if source_tool_name and record.tool_name != source_tool_name:
                return None
            source = record.source
            if source.version_policy in (
                SourceVersionPolicy.PROBEABLE,
                SourceVersionPolicy.VERSIONED,
            ) and not source.version_token:
                return None
            state = tool.freshness.refresh(owner=owner, evidence_ref=ref)
            if state.availability is not AvailabilityState.AVAILABLE:
                return None
            if (
                source.kind is SourceKind.FILE
                and source.version_policy is SourceVersionPolicy.PROBEABLE
                and state.freshness is not FreshnessState.VERIFIED_CURRENT
            ):
                return None
            probe = tool.hydration.read(
                owner=owner,
                evidence_ref=ref,
                range_type=RangeType.TEXT_CHAR,
                start=0,
                limit=1,
            )
            if probe.blob_sha256 != record.blob_ref.sha256:
                return None
            capsules[tool_id] = json.dumps(
                {
                    "schema": "lfl_exact_tool_observation_ref_v1",
                    "tool_call_id": tool_id,
                    "evidence_ref": ref.ref,
                    "read_tool": "read_evidence",
                    "range_type": "text_char",
                    "start": 0,
                    "limit_max": tool.hydration.max_limit,
                    "original_chars": record.blob_ref.size_chars,
                    "blob_sha256": record.blob_ref.sha256,
                    "source_kind": source.kind.value,
                    "version_policy": source.version_policy.value,
                    "version_token": source.version_token,
                    "freshness": state.freshness.value,
                    "inline_complete": False,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        if set(capsules) != set(ids):
            return None
        # Rebuild from the exact durable Session tool-call group, not from a
        # model-written summary or a ref-looking string in old provider history.
        if not group_visible_in_provider_view(
            group, raw_messages, active_ingress_ref=active_ingress_ref
        ):
            return None
        candidate = [dict(row) for row in raw_messages]
        ingress_index = next(
            (
                i for i, row in enumerate(candidate)
                if str(row.get("_active_run_ingress_ref") or "") == active_ingress_ref
            ),
            -1,
        )
        if ingress_index < 0:
            return None
        replaced = False
        for i in range(ingress_index + 1, len(candidate)):
            if _role(candidate[i]) != "assistant" or _calls(candidate[i]) != group["calls"]:
                continue
            segment = candidate[i + 1 : i + 1 + len(ids)]
            if (
                len(segment) != len(ids)
                or any(_role(row) != "tool" for row in segment)
                or {str(row.get("tool_call_id") or "") for row in segment} != set(ids)
            ):
                continue
            if any(
                str(row.get("content") or "") != group["receipts"][str(row.get("tool_call_id"))]
                for row in segment
            ):
                continue
            for row in segment:
                row["content"] = capsules[str(row["tool_call_id"])]
            replaced = True
            break
        if not replaced:
            return None
        projected_chars = sum(dict_wire_chars(row) for row in candidate)
        if physical_limit and projected_chars > effective_budget:
            return None
        if callable(request_preflight):
            preflight = request_preflight(candidate, tools_param, model=chat_model_arg)
            if not isinstance(preflight, Mapping) or bool(preflight.get("hard_overflow", False)):
                return None
        # The provider view must contain exactly the qualified refs in paired
        # tool messages after the active ingress; storage alone never suffices.
        for tool_id, capsule in capsules.items():
            if not any(
                row.get("role") == "tool"
                and row.get("tool_call_id") == tool_id
                and row.get("content") == capsule
                for row in candidate[ingress_index + 1 :]
            ):
                return None
        return candidate, projected_chars
    except (EvidenceError, ValueError, KeyError, TypeError, OSError):
        return None
