#!/usr/bin/env python3
"""Read-only T1 crash preflight: a NEW operator authorization, never old-Run replay.

This is an advisory gate, not a runtime authorization. The operator must
separately create a fresh Session and a fresh 0600 T1 one-shot configuration.
No model, tool, authorization or workspace write occurs here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_dispatch import exact_workspace_scope
from llm_loop.resources.task_budget_store import TaskBudgetStore

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ALLOWED_TOOLS = {"read_file", "edit_file"}


class RecoveryHoldError(Exception):
    """An unsafe or unproven preflight condition."""


def _hold(reason: str) -> None:
    raise RecoveryHoldError(reason)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Read-only T1 post-crash operator preflight")
    for name in (
        "--data-dir", "--workspace-root", "--source-session-id",
        "--source-authorization-id", "--source-run-generation", "--target-path",
        "--expected-target-sha256", "--new-session-id",
    ):
        ap.add_argument(name, required=True)
    ap.add_argument("--old-host-stopped-attested", action="store_true")
    ap.add_argument("--json", action="store_true", required=True, help="Required: one-line JSON output")
    return ap.parse_args(argv)


def _validate_args(a: argparse.Namespace) -> None:
    if (
        not a.source_session_id or len(a.source_session_id) > 128
        or not a.new_session_id or len(a.new_session_id) > 128
        or a.source_session_id == a.new_session_id
    ):
        _hold("invalid_or_reused_session_id")
    if not _HEX32.fullmatch(a.source_authorization_id):
        _hold("invalid_source_authorization_id")
    if not _HEX32.fullmatch(a.source_run_generation):
        _hold("invalid_source_run_generation")
    if not _HEX64.fullmatch(a.expected_target_sha256):
        _hold("invalid_expected_target_sha256")
    if not a.old_host_stopped_attested:
        _hold("old_host_stop_attestation_required")


def _validate_target(a: argparse.Namespace) -> tuple[Path, Path, str]:
    raw_root = Path(a.workspace_root)
    raw_data = Path(a.data_dir)
    relative = Path(a.target_path)
    if (
        not raw_root.is_absolute() or not raw_data.is_absolute()
        or not a.target_path or relative.is_absolute()
        or a.target_path.startswith(("~", "./"))
        or "\\" in a.target_path or "//" in a.target_path
        or any(p in {"..", "."} for p in relative.parts)
        or a.target_path.endswith("/")
    ):
        _hold("invalid_or_escaping_target_path")
    try:
        root = raw_root.resolve(strict=True)
        if not root.is_dir() or root != raw_root or raw_root.is_symlink():
            _hold("workspace_not_canonical_directory")
        if not raw_data.resolve(strict=True).is_dir():
            _hold("data_dir_unavailable")
        target = root / relative
        if not target.is_file() or target.is_symlink():
            _hold("target_not_regular_file")
        if target.resolve(strict=True) != target:
            _hold("target_symlink_component")
        if not stat.S_ISREG(os.lstat(target).st_mode):
            _hold("target_not_regular_file")
        if target.stat().st_size > 2 * 1024 * 1024:
            _hold("target_exceeds_t1_size_limit")
        if not target.is_relative_to(root):
            _hold("target_outside_workspace")
        # No path walk through a symlink, including an intermediate directory.
        if any(part.is_symlink() for part in (target, *target.parents) if part != root and root in part.parents):
            _hold("target_symlink_component")
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
    except (OSError, ValueError):
        _hold("workspace_or_target_unavailable")
    if digest != a.expected_target_sha256:
        _hold("target_sha256_drift")
    return root, target, digest


def _budget_checks(a: argparse.Namespace, root: Path) -> tuple[TaskBudgetStore, dict[str, Any], dict[str, Any]]:
    budget_id = "webt1-" + a.source_authorization_id
    store = TaskBudgetStore(Path(a.data_dir) / "task_budget_t1_web")
    try:
        budget = store.read(budget_id)
        report = store.report(budget_id)
    except Exception:
        _hold("source_budget_missing_or_corrupt")
    grant = budget["grant"]
    member = budget["members"].get(budget_id)
    if (
        budget["phase"] != "closed_uncertain"
        or grant["budget_id"] != budget_id
        or grant["profile"] != "web-glm-t1-budgeted-write-v1"
        or grant["session_id"] != a.source_session_id
        or grant["workspace_scope"] != exact_workspace_scope(str(root))
        or grant["provider_identity"] != "glm"
        or grant["exact_model_ref"] != "glm-5.3"
        or grant["surface"] != "web"
        or not isinstance(member, dict)
        or member["run_generation"] != a.source_run_generation
        or member["session_id"] != a.source_session_id
    ):
        _hold("source_budget_identity_or_phase_mismatch")
    cap = grant["capabilities"]
    lim = grant["limits"]
    if (
        set(cap["allowed_tools"] or ()) != _ALLOWED_TOOLS
        or cap["allow_wake"] or cap["allow_subagents"]
        or lim["physical_attempts"] != 4
        or lim["tool_invocations"] != 3
    ):
        _hold("source_budget_capabilities_drift")
    reservations = budget["reservations"]
    if not reservations or report["outstanding_or_unknown"]:
        _hold("source_budget_has_unsettled_liability")
    if report["over_limit_dimensions"]:
        _hold("source_budget_exceeded")
    for row in reservations.values():
        if row["run_generation"] != a.source_run_generation:
            _hold("source_reservation_generation_mismatch")
        if row["phase"] not in {"settled", "aborted_before_dispatch"}:
            _hold("source_reservation_unsettled")
        if row["phase"] == "settled" and row["outcome"] != "success":
            _hold("source_reservation_not_success")
    return store, budget, report


def _event_checks(
    a: argparse.Namespace, root: Path, target: Path, budget: dict[str, Any],
) -> tuple[dict[str, int], list[tuple[str, int, str, dict[str, Any]]]]:
    event_dir = Path(a.data_dir) / "event_logs"
    if not event_dir.is_dir():
        _hold("source_event_store_missing")
    try:
        events = EventStore(event_dir, enabled=True).read(a.source_session_id)
    except Exception:
        _hold("source_event_store_unavailable")
    if not events:
        _hold("source_event_log_missing")
    # Never ignore an unrecognized provider/tool/run event that may represent
    # a failed, cancelled or still-running physical action.
    allowed = {
        "provider.call.opened", "provider.call.settled",
        "provider.transport.opened", "provider.transport.settled",
        "provider.structure.validated",
        "tool.execution.declared", "tool.execution.started",
        "tool.execution.finished", "tool.execution.receipt_committed",
        "tool.execution.effect_prepared", "tool.execution.effect_observed",
        "llm.partial_checkpoint",
    }
    calls: dict[str, str] = {}
    call_settled: dict[str, dict[str, Any]] = {}
    opened: dict[str, Any] = {}
    settled: dict[str, Any] = {}
    tool_facts: dict[str, dict[str, dict[str, Any]]] = {
        name: {} for name in (
            "tool.execution.declared", "tool.execution.started",
            "tool.execution.finished", "tool.execution.receipt_committed",
            "tool.execution.effect_prepared",
        )
    }
    effects: list[dict[str, Any]] = []
    for event in events:
        kind = event.type
        payload = event.payload if isinstance(event.payload, dict) else {}
        if kind == "run.end":
            _hold("source_run_already_ended")
        if kind.startswith(("provider.", "tool.", "run.", "llm.")) and kind not in allowed:
            _hold("unknown_evidence_event_kind")
        if kind == "provider.structure.validated":
            if payload.get("valid") is not True:
                _hold("provider_structure_invalid")
        elif kind == "provider.call.opened":
            call_id = payload.get("call_id")
            generation = payload.get("origin_run_generation")
            if not call_id or call_id in calls or generation != a.source_run_generation:
                _hold("provider_call_generation_or_identity_mismatch")
            calls[call_id] = generation
        elif kind == "provider.call.settled":
            call_id = payload.get("call_id")
            if not call_id or call_id in call_settled or payload.get("outcome") != "success":
                _hold("provider_call_not_successfully_settled")
            call_settled[call_id] = payload
        elif kind in {"provider.transport.opened", "provider.transport.settled"}:
            attempt_id = payload.get("attempt_id")
            if (
                not isinstance(attempt_id, str) or not attempt_id
                or payload.get("provider_id") != "glm"
                or payload.get("model_id") != "glm-5.3"
            ):
                _hold("provider_transport_identity_mismatch")
            table = opened if kind.endswith("opened") else settled
            if attempt_id in table:
                _hold("duplicate_provider_transport_attempt")
            table[attempt_id] = event
        elif kind.startswith("tool.execution."):
            execution_id = payload.get("execution_id")
            if (
                not isinstance(execution_id, str) or not execution_id
                or payload.get("origin_run_generation") != a.source_run_generation
                or payload.get("tool_name") not in _ALLOWED_TOOLS
            ):
                _hold("tool_execution_identity_mismatch")
            if kind == "tool.execution.effect_observed":
                effects.append(payload)
                continue
            table = tool_facts[kind]
            if execution_id in table:
                _hold("duplicate_tool_execution_fact")
            table[execution_id] = payload
            if kind == "tool.execution.finished" and payload.get("status") != "success":
                _hold("tool_execution_finished_not_success")
            if kind == "tool.execution.receipt_committed" and payload.get("outcome") not in (None, "success"):
                _hold("tool_receipt_outcome_mismatch")
    if not opened or set(opened) != set(settled):
        _hold("provider_transport_unsettled_or_missing")
    if set(calls) != set(call_settled):
        _hold("provider_call_unsettled_or_missing")
    if set(calls) != {e.payload.get("call_id") for e in opened.values()}:
        _hold("provider_call_without_transport")
    for attempt_id, opened_event in opened.items():
        opened_fact = opened_event.payload
        settled_event = settled[attempt_id]
        settled_fact = settled_event.payload
        call_id = opened_fact.get("call_id")
        if (
            call_id not in calls or settled_fact.get("call_id") != call_id
            or settled_fact.get("outcome") != "success"
            or settled_fact.get("status_code") != 200
            or settled_fact.get("usage_observations") != 1
        ):
            _hold("provider_transport_unqualified_settlement")
    declared = tool_facts["tool.execution.declared"]
    started = tool_facts["tool.execution.started"]
    finished = tool_facts["tool.execution.finished"]
    committed = tool_facts["tool.execution.receipt_committed"]
    prepared = tool_facts["tool.execution.effect_prepared"]
    if not started or set(started) != set(finished) or set(started) != set(committed):
        _hold("tool_execution_uncommitted")
    if declared and set(declared) != set(started):
        _hold("tool_execution_declared_not_started")
    for execution_id, item in started.items():
        if (
            item["tool_name"] != finished[execution_id]["tool_name"]
            or item["tool_name"] != committed[execution_id]["tool_name"]
            or not _HEX64.fullmatch(str(finished[execution_id].get("result_state_sha256") or ""))
            or finished[execution_id].get("result_state_sha256")
            != committed[execution_id].get("result_state_sha256")
        ):
            _hold("tool_receipt_finished_mismatch")
    if Counter(x["tool_name"] for x in started.values()) != Counter({"read_file": 1, "edit_file": 1}):
        _hold("source_tool_sequence_not_one_read_one_edit")
    if len(effects) != 1 or len(prepared) != 1:
        _hold("source_edit_effect_count_mismatch")
    effect = effects[0]
    execution_id = effect["execution_id"]
    prep = prepared.get(execution_id)
    if (
        effect["tool_name"] != "edit_file"
        or execution_id not in committed
        or started[execution_id]["tool_name"] != "edit_file"
        or prep is None
        or prep.get("canonical_path") != str(target)
        or prep.get("workspace_root") != str(root)
        or prep.get("expected_after_sha256") != a.expected_target_sha256
        or effect.get("canonical_path") != str(target)
        or effect.get("workspace_root") != str(root)
        or effect.get("actual_after_sha256") != a.expected_target_sha256
        or effect.get("matches_expected") is not True
    ):
        _hold("source_edit_effect_not_durably_verified")
    rows = tuple(budget["reservations"].items())
    provider_rows = [x for _, x in rows if x["kind"] == "physical_attempts" and x["phase"] == "settled"]
    tool_rows = [(rid, x) for rid, x in rows if x["kind"] == "tool_invocations" and x["phase"] == "settled"]
    if len(provider_rows) != len(opened) or len(tool_rows) != len(committed):
        _hold("source_event_budget_count_mismatch")
    # Real T1 provider settlement receipt encodes the exact EventStore
    # provider.transport.settled event_id. A count-only join is not enough.
    event_ids = {e.event_id for e in settled.values()}
    bound_ids: list[str] = []
    for row in provider_rows:
        parts = str(row["receipt_ref"]).split(":")
        if len(parts) != 3 or parts[0] != "webt1ev" or len(parts[2]) != 16:
            _hold("provider_budget_receipt_not_bound")
        bound_ids.append(parts[1])
    if set(bound_ids) != event_ids or len(set(bound_ids)) != len(bound_ids):
        _hold("provider_budget_event_identity_mismatch")
    if (
        Counter(x["tool_id"] for _, x in tool_rows)
        != Counter(x["tool_name"] for x in committed.values())
        or any(x["receipt_ref"] != f"dispatch-receipt-{rid}" for rid, x in tool_rows)
    ):
        _hold("tool_budget_receipt_identity_mismatch")
    signature = [(e.event_id, e.seq, e.type, e.payload) for e in events]
    return {
        "provider_attempts": len(opened),
        "tool_receipts": len(committed),
        "observed_edits": 1,
    }, signature


def evaluate(a: argparse.Namespace) -> dict[str, Any]:
    _validate_args(a)
    root, target, sha = _validate_target(a)
    store, budget, _ = _budget_checks(a, root)
    counts, event_signature = _event_checks(a, root, target, budget)
    # No silent pass if the durable ledger changes while it is being examined.
    if store.read(budget["grant"]["budget_id"]) != budget:
        _hold("source_budget_changed_during_preflight")
    if hashlib.sha256(target.read_bytes()).hexdigest() != sha:
        _hold("target_changed_during_preflight")
    event_dir = Path(a.data_dir) / "event_logs"
    try:
        reread = EventStore(event_dir, enabled=True).read(a.source_session_id)
    except Exception:
        _hold("source_events_changed_during_preflight")
    if [(e.event_id, e.seq, e.type, e.payload) for e in reread] != event_signature:
        _hold("source_events_changed_during_preflight")
    return {
        "status": "PREFLIGHT_PASS_OPERATOR_ACTION_REQUIRED",
        "eligible_for_new_authorization": True,
        "preflight_only": True,
        "new_session_id": a.new_session_id,
        "source_session_id": a.source_session_id,
        "source_run_generation": a.source_run_generation,
        "target_path": a.target_path,
        "target_sha256": sha,
        "source_budget_phase": budget["phase"],
        "reconciled": counts,
        "old_host_stopped": "operator_attested_not_independently_verified",
        "physical_quiescence_verified": False,
        "next_action": "Operator separately provisions a NEW session, NEW one-shot authorization, and current target SHA; no automatic replay",
    }


def main(argv: list[str] | None = None) -> int:
    try:
        result = evaluate(_parse_args(argv))
    except RecoveryHoldError as exc:
        result = {"status": "HOLD", "eligible_for_new_authorization": False, "reason": str(exc)}
    except Exception:
        result = {"status": "HOLD", "eligible_for_new_authorization": False, "reason": "unavailable_or_invalid_evidence"}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["eligible_for_new_authorization"] else 2


if __name__ == "__main__":
    sys.exit(main())
