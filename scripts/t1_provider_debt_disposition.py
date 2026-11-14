#!/usr/bin/env python3
"""Read-only, fail-closed disposition of a crashed T1 Provider attempt.

This is an evidence verifier, NOT a Provider settlement, billing receipt,
new authorization, or automatic Run recovery mechanism. Exit 2 means that
consistent evidence still requires HOLD. Exit 3 means evidence is invalid.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_dispatch import exact_workspace_scope
from llm_loop.resources.task_budget_store import TaskBudgetStore

_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class EvidenceInvalidError(Exception):
    """Evidence is unavailable, inconsistent, or changed during inspection."""


class _HoldParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise EvidenceInvalidError("invalid_cli_arguments")


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise EvidenceInvalidError(code)


def _digest(path: Path, max_bytes: int) -> str:
    _require(path.is_file() and not path.is_symlink(), "missing_or_symlink_evidence")
    _require(path.stat().st_size <= max_bytes, "evidence_size_limit")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_dir(value: str) -> Path:
    path = Path(value)
    _require(path.is_absolute() and path.is_dir() and not path.is_symlink(), "invalid_directory")
    _require(path.resolve(strict=True) == path, "noncanonical_directory")
    return path


def _target(root: Path, relative: str) -> Path:
    p = Path(relative)
    _require(
        bool(relative) and not p.is_absolute() and not relative.startswith(("~", "./"))
        and chr(92) not in relative and chr(0) not in relative
        and all(part not in {"", ".", ".."} for part in relative.split("/")),
        "unsafe_target_path",
    )
    target = root / p
    _require(target.is_file() and not target.is_symlink(), "target_missing_or_symlink")
    _require(target.resolve(strict=True) == target, "target_symlink_component")
    _require(target.is_relative_to(root), "target_outside_workspace")
    return target


def inspect(args: argparse.Namespace) -> dict[str, Any]:
    _require(bool(_HEX32.fullmatch(args.source_authorization_id)), "invalid_authorization")
    _require(bool(_HEX32.fullmatch(args.source_run_generation)), "invalid_run_generation")
    for name in ("expected_events_sha256", "expected_budget_sha256", "expected_target_sha256"):
        _require(bool(_HEX64.fullmatch(getattr(args, name))), "invalid_expected_digest")
    _require(
        bool(re.fullmatch(r"[0-9a-f-]{36}", args.source_session_id)),
        "invalid_session_id",
    )
    data = _canonical_dir(args.data_dir)
    workspace = _canonical_dir(args.workspace_root)
    target = _target(workspace, args.target_path)
    event_path = data / "event_logs" / (args.source_session_id + ".jsonl")
    _require(event_path.parent.is_dir() and not event_path.parent.is_symlink(), "event_dir_invalid")
    budget_id = "webt1-" + args.source_authorization_id
    budget_dir = data / "task_budget_t1_web"
    _require(budget_dir.is_dir() and not budget_dir.is_symlink(), "budget_dir_invalid")
    budget_candidates: list[Path] = []
    for path in budget_dir.glob("budget-*.json"):
        _require(not path.is_symlink(), "budget_symlink")
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise EvidenceInvalidError("budget_file_invalid") from exc
        if (row.get("grant") or {}).get("budget_id") == budget_id:
            budget_candidates.append(path)
    _require(len(budget_candidates) == 1, "budget_identity_not_unique")
    budget_path = budget_candidates[0]
    files = {"events": event_path, "budget": budget_path, "target": target}
    before = {
        name: _digest(path, 8 * 1024 * 1024 if name == "events" else 2 * 1024 * 1024)
        for name, path in files.items()
    }
    _require(before["events"] == args.expected_events_sha256, "events_sha_mismatch")
    _require(before["budget"] == args.expected_budget_sha256, "budget_sha_mismatch")
    _require(before["target"] == args.expected_target_sha256, "target_sha_mismatch")

    try:
        store = TaskBudgetStore(budget_dir)
        row = store.read(budget_id)
        report = store.report(budget_id)
        events = EventStore(event_path.parent, enabled=True).read(args.source_session_id)
    except Exception as exc:
        raise EvidenceInvalidError("source_authority_unavailable_or_corrupt") from exc
    _require(bool(events), "events_empty")
    _require(len(events) == len(event_path.read_text(encoding="utf-8").splitlines()), "event_count_mismatch")
    grant = row["grant"]
    member = row["members"].get(budget_id)
    _require(
        row["phase"] == "closed_uncertain"
        and grant["session_id"] == args.source_session_id
        and grant["workspace_scope"] == exact_workspace_scope(str(workspace))
        and grant["provider_identity"] == "glm"
        and grant["exact_model_ref"] == "glm-5.3"
        and grant["surface"] == "web"
        and grant["profile"] == "web-glm-t1-budgeted-write-v1"
        and isinstance(member, dict)
        and member.get("run_generation") == args.source_run_generation,
        "budget_identity_or_phase_mismatch",
    )
    reservations = row["reservations"]
    _require(isinstance(reservations, dict) and len(reservations) == 5, "reservation_count_mismatch")
    physical = {k: v for k, v in reservations.items() if v.get("kind") == "physical_attempts"}
    tools = {k: v for k, v in reservations.items() if v.get("kind") == "tool_invocations"}
    _require(len(physical) == 3 and len(tools) == 2, "reservation_kind_count_mismatch")
    _require(
        Counter(v.get("tool_id") for v in tools.values())
        == Counter({"read_file": 1, "edit_file": 1})
        and all(v.get("receipt_ref") == "dispatch-receipt-" + rid
                for rid, v in tools.items()),
        "tool_budget_receipt_mismatch",
    )
    _require(
        all(v.get("run_generation") == args.source_run_generation for v in reservations.values()),
        "reservation_run_generation_mismatch",
    )
    unsettled = {k: v for k, v in physical.items() if v.get("phase") != "settled"}
    _require(len(unsettled) == 1, "unsettled_reservation_count_mismatch")
    reservation_id, debt = next(iter(unsettled.items()))
    _require(
        debt.get("phase") == "dispatched"
        and not debt.get("receipt_ref")
        and not debt.get("outcome")
        and all(v.get("phase") == "settled" and v.get("outcome") == "success"
                for k, v in physical.items() if k != reservation_id)
        and all(v.get("phase") == "settled" and v.get("outcome") == "success"
                for v in tools.values()),
        "unexpected_reservation_state",
    )
    _require(
        report["phase"] == "closed_uncertain"
        and report["outstanding_or_unknown"] == [reservation_id]
        and report["physical_quiescence_verified"] is False
        and not report["over_limit_dimensions"]
        and report["used_or_reserved"]["physical_attempts"] == 3
        and report["used_or_reserved"]["tool_invocations"] == 2,
        "budget_report_inconsistent",
    )

    allowed_events = {
        "session.created", "message.appended", "knowledge.discovery",
        "provider.call.opened", "provider.call.settled",
        "provider.structure.validated", "provider.transport.opened",
        "provider.transport.settled", "request.meta", "request.usage",
        "cache.window", "llm.partial_checkpoint",
        "tool.execution.declared", "tool.execution.started",
        "tool.execution.finished", "tool.execution.receipt_committed",
        "tool.execution.effect_prepared", "tool.execution.effect_observed",
    }
    _require(all(e.type in allowed_events for e in events), "unrecognized_action_event")
    _require(
        len({e.event_id for e in events}) == len(events)
        and all(e.seq == index for index, e in enumerate(events, 1)),
        "event_identity_or_sequence_invalid",
    )
    counts = Counter(event.type for event in events)
    _require(
        counts["provider.call.opened"] == 3
        and counts["provider.call.settled"] == 2
        and counts["provider.transport.opened"] == 3
        and counts["provider.transport.settled"] == 2
        and counts["tool.execution.receipt_committed"] == 2
        and counts["tool.execution.effect_observed"] == 1
        and counts["run.end"] == 0,
        "event_counts_inconsistent",
    )
    opened = {
        e.payload["attempt_id"]: e
        for e in events if e.type == "provider.transport.opened"
    }
    settled = {
        e.payload["attempt_id"]: e
        for e in events if e.type == "provider.transport.settled"
    }
    _require(len(opened) == 3 and len(settled) == 2, "duplicate_transport_attempt")
    _require(
        all(e.payload.get("provider_id") == "glm"
                and e.payload.get("model_id") == "glm-5.3" for e in (*opened.values(), *settled.values())),
        "provider_transport_identity_invalid",
    )
    _require(set(settled).issubset(opened), "settled_transport_not_opened")
    missing = set(opened) - set(settled)
    _require(len(missing) == 1, "unmatched_transport_count")
    attempt_id = next(iter(missing))
    call_id = opened[attempt_id].payload["call_id"]
    calls = {
        e.payload["call_id"]: e
        for e in events if e.type == "provider.call.opened"
    }
    completed_calls = {
        e.payload["call_id"]: e
        for e in events if e.type == "provider.call.settled"
    }
    _require(len(calls) == 3 and len(completed_calls) == 2, "duplicate_provider_call")
    _require(
        call_id in calls and call_id not in completed_calls
        and calls[call_id].payload.get("origin_run_generation") == args.source_run_generation
        and {opened[k].payload["call_id"] for k in settled} == set(completed_calls)
        and all(e.payload.get("outcome") == "success" for e in completed_calls.values())
        and all(settled[k].payload.get("call_id") == opened[k].payload.get("call_id")
                and settled[k].payload.get("outcome") == "success"
                and settled[k].payload.get("status_code") == 200
                and settled[k].payload.get("usage_observations") == 1
                for k in settled),
        "provider_call_transport_join_invalid",
    )
    receipt_ids: list[str] = []
    for reservation in physical.values():
        if reservation["phase"] != "settled":
            continue
        ref = str(reservation["receipt_ref"]).split(":")
        _require(
            len(ref) == 3 and ref[0] == "webt1ev"
            and bool(re.fullmatch(r"[0-9a-f]{16}", ref[2])),
            "settled_receipt_format_invalid",
        )
        receipt_ids.append(ref[1])
    _require(
        len(set(receipt_ids)) == 2
        and set(receipt_ids) == {e.event_id for e in settled.values()},
        "settled_receipt_event_join_invalid",
    )
    tool_types = (
        "tool.execution.declared", "tool.execution.started",
        "tool.execution.finished", "tool.execution.receipt_committed",
    )
    tool_rows = {
        kind: {
            e.payload.get("execution_id"): e.payload
            for e in events if e.type == kind
        }
        for kind in tool_types
    }
    started = tool_rows["tool.execution.started"]
    _require(
        len(started) == 2
        and all(set(table) == set(started) for table in tool_rows.values())
        and Counter(v.get("tool_name") for v in started.values())
        == Counter({"read_file": 1, "edit_file": 1}),
        "tool_receipt_chain_invalid",
    )
    _require(
        all(
            all(table[ident].get("tool_name") == fact["tool_name"]
                for table in tool_rows.values())
            and fact.get("origin_run_generation") == args.source_run_generation
            and tool_rows["tool.execution.finished"][ident].get("status") == "success"
            and bool(_HEX64.fullmatch(str(
                tool_rows["tool.execution.finished"][ident].get("result_state_sha256") or ""
            )))
            and tool_rows["tool.execution.finished"][ident].get("result_state_sha256")
            == tool_rows["tool.execution.receipt_committed"][ident].get("result_state_sha256")
            and tool_rows["tool.execution.receipt_committed"][ident].get("outcome")
            in (None, "success")
            for ident, fact in started.items()
        ),
        "tool_run_identity_invalid",
    )
    effects = [e.payload for e in events if e.type == "tool.execution.effect_observed"]
    prepared = [e.payload for e in events if e.type == "tool.execution.effect_prepared"]
    _require(
        len(prepared) == 1 and len(effects) == 1
        and prepared[0].get("execution_id") == effects[0].get("execution_id")
        and effects[0].get("execution_id") in started
        and started[effects[0]["execution_id"]].get("tool_name") == "edit_file"
        and prepared[0].get("expected_after_sha256") == before["target"]
        and prepared[0].get("canonical_path") == str(target)
        and effects[0].get("actual_after_sha256") == before["target"]
        and effects[0].get("matches_expected") is True
        and effects[0].get("canonical_path") == str(target),
        "tool_effect_target_mismatch",
    )
    after = {
        name: _digest(path, 8 * 1024 * 1024 if name == "events" else 2 * 1024 * 1024)
        for name, path in files.items()
    }
    _require(before == after, "source_changed_during_audit")
    unmatched = opened[attempt_id].payload
    remote_id_present = any(
        isinstance(unmatched.get(key), str) and bool(unmatched[key])
        for key in ("provider_request_id", "upstream_request_id", "response_id")
    )
    return {
        "schema": "lfl.t1.provider_debt_disposition.audit.v1",
        "audit_status": "PASS_EVIDENCE_CONSISTENT",
        "disposition": "QUARANTINED_UNRESOLVED",
        "source_budget_phase": "closed_uncertain",
        "source_session_id": args.source_session_id,
        "source_run_generation": args.source_run_generation,
        "budget_id": budget_id,
        "unsettled_reservation_id": reservation_id,
        "unsettled_attempt_id": attempt_id,
        "unsettled_call_id": call_id,
        "provider_opened": 3,
        "provider_settled": 2,
        "tool_receipts": 2,
        "tool_effect_observed": 1,
        "source_run_end_count": 0,
        "provider_remote_request_id_present": remote_id_present,
        "reservation_attempt_binding": "unique_remainder_only_not_a_provider_receipt",
        "evidence_sha256": before,
        "source_unchanged_during_audit": True,
        "physical_quiescence_verified": False,
        "provider_billing_settled": False,
        "source_run_replay_allowed": False,
        "source_budget_reuse_allowed": False,
        "automatic_resume_allowed": False,
        "new_authorization_issued": False,
        "external_provider_calls": 0,
        "tool_invocations": 0,
        "source_ledger_mutations": 0,
        "next_action": (
            "Preserve old root as closed_uncertain. Only independently "
            "authenticated, attempt-bound Provider evidence may justify "
            "separate future adjudication; this audit cannot settle or refund."
        ),
    }


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = _HoldParser(description=__doc__)
    for name in (
        "data-dir", "workspace-root", "source-session-id",
        "source-authorization-id", "source-run-generation", "target-path",
        "expected-events-sha256", "expected-budget-sha256", "expected-target-sha256",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--json", action="store_true", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        result = inspect(_args(argv))
    except EvidenceInvalidError as exc:
        result = {
            "schema": "lfl.t1.provider_debt_disposition.audit.v1",
            "audit_status": "HOLD_INVALID_EVIDENCE",
            "reason": str(exc),
            "source_run_replay_allowed": False,
            "provider_billing_settled": False,
        }
        exit_code = 3
    except Exception:
        result = {
            "schema": "lfl.t1.provider_debt_disposition.audit.v1",
            "audit_status": "HOLD_UNAVAILABLE_OR_INVALID_EVIDENCE",
            "source_run_replay_allowed": False,
            "provider_billing_settled": False,
        }
        exit_code = 3
    else:
        exit_code = 2  # A successful audit still means HOLD, NEVER admission.
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
