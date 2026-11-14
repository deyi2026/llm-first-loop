"""M5-D explicit read-only Web recovery inspection, never a Run dispatcher."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from llm_loop.core.durable_effect_evidence import inspect_run_effect_evidence
from llm_loop.core.durable_run_recovery import (
    HOLD,
    OPENED,
    _strict_snapshot,
    assess_durable_run,
)
from llm_loop.resources.task_budget_store import TaskBudgetStore

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")


def _hold(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "decision": HOLD,
        "reason": reason,
        "read_only": True,
        "auto_resume_allowed": False,
        "old_run_replay_allowed": False,
        "provider": {},
        "tool": {},
    }


def durable_recovery_view(engine: Any, session_id: str) -> dict[str, Any]:
    """Inspect exactly one T1 Run identity from strict facts, no query secrets.

    This is a deliberate, low-frequency operator view. The existing
    /continuity hot-path must not perform these full raw JSONL captures.
    """
    event_store = getattr(engine, "_event_store", None)
    if event_store is None or not getattr(event_store, "enabled", False):
        event_store = getattr(getattr(engine, "session", None), "_event_store", None)
    if event_store is None or not getattr(event_store, "enabled", False):
        return _hold("event_store_unavailable")
    try:
        events, _ = _strict_snapshot(event_store, session_id)
    except (OSError, ValueError, TypeError, RuntimeError):
        return _hold("event_source_unverifiable")
    opened = [e for e in events if e.type == OPENED]
    if len(opened) != 1:
        return _hold(
            "no_durable_run_identity" if not opened else "ambiguous_durable_run_identity"
        )
    payload = opened[0].payload
    generation = payload.get("run_generation")
    authorization_id = payload.get("authorization_id")
    if (
        not isinstance(generation, str)
        or not _HEX32.fullmatch(generation)
        or not isinstance(authorization_id, str)
        or not _HEX32.fullmatch(authorization_id)
    ):
        return _hold("invalid_durable_run_identity")
    data_dir = getattr(getattr(engine, "settings", None), "data_dir", None)
    if not isinstance(data_dir, str) or not data_dir:
        return _hold("budget_store_unavailable")
    budget_store = TaskBudgetStore(Path(data_dir) / "task_budget_t1_web")
    recovery = assess_durable_run(
        event_store=event_store,
        budget_store=budget_store,
        session_id=session_id,
        run_generation=generation,
        authorization_id=authorization_id,
    )
    effects = inspect_run_effect_evidence(
        event_store=event_store,
        budget_store=budget_store,
        session_id=session_id,
        run_generation=generation,
        authorization_id=authorization_id,
    )
    return {
        "available": True,
        "decision": recovery.decision,
        "reason": recovery.reason,
        "effect_reason": effects.reason,
        "budget_phase": effects.budget_phase,
        "budget_revision": effects.budget_revision,
        "event_snapshot_sha256": recovery.event_snapshot_sha256,
        "read_only": True,
        "auto_resume_allowed": False,
        "old_run_replay_allowed": False,
        "remote_provider_settlement_proven": False,
        "tool_effect_causation_proven": False,
        "provider": {
            "calls_opened": effects.provider_calls_opened,
            "transports_opened": effects.provider_transport_opened,
            "transports_settled": effects.provider_transport_settled,
            "transports_unsettled": effects.provider_transport_unsettled,
            "budget_unsettled": effects.provider_budget_unsettled,
            "local_receipts_joined": effects.provider_local_receipts_joined,
        },
        "tool": {
            "budget_invocations": effects.tool_budget_invocations,
            "receipts_committed": effects.tool_receipts_committed,
            "effects_prepared": effects.tool_effect_prepared,
            "effects_observed": effects.tool_effect_observed,
            "effect_pairs_observed": effects.tool_effect_pairs_observed,
            "effects_unresolved": effects.tool_effect_unresolved,
        },
    }
