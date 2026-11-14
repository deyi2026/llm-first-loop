"""M5-A advisory, fail-closed cross-process Run recovery projection.

This reader has NO admission, retry, replay, provider, tool, or budget-mutation
authority. Only a future fully fenced execution entrypoint may emit the
strict run.durable.* protocol; legacy runs always remain UNKNOWN/HOLD.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from llm_loop.event_log.model import Event

if TYPE_CHECKING:
    from llm_loop.event_log.store import EventStore
    from llm_loop.resources.task_budget_store import TaskBudgetStore

SCHEMA = "lfl.m5.durable_run/v1"
OPENED = "run.durable.opened"
FENCED = "run.durable.admission_fenced"
TERMINAL = "run.durable.terminal"
HOLD = "unknown_HOLD"
COMPLETED = "completed_verified"
REPLAN = "safe_to_replan_verified"


@dataclass(frozen=True)
class RunRecoveryAssessment:
    decision: str
    reason: str
    session_id: str
    run_generation: str
    authorization_id: str
    budget_id: str
    event_snapshot_sha256: str = ""
    budget_revision: int | None = None
    # This is a read-only observation, NEVER an instruction to run anything.
    auto_resume_allowed: bool = False
    old_run_replay_allowed: bool = False


def _strict_snapshot(store: EventStore, session_id: str) -> tuple[list[Event], str]:
    """Reject incomplete/corrupt/aliased event files instead of skipping rows."""
    files = store.read_source_files(session_id)
    if not files:
        raise ValueError("event_source_missing")
    events: list[Event] = []
    ids: set[str] = set()
    digest = hashlib.sha256()
    root = store._dir.resolve()  # noqa: SLF001 - exact source trust root
    for relative, raw in files:
        segment = Path(relative)
        if segment.is_absolute() or ".." in segment.parts:
            raise ValueError("event_source_path_escape")
        path = store._dir / segment  # noqa: SLF001 - exact source-file trust check
        path.resolve(strict=True).relative_to(root)
        before = os.lstat(path)
        with os.fdopen(
            os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)), "rb"
        ) as source:
            info = os.fstat(source.fileno())
            if (
                (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino)
                or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_nlink != 1
                or info.st_mode & 0o022
            ):
                raise ValueError("event_source_not_trusted")
            if source.read() != raw:
                raise ValueError("event_source_changed_during_capture")
        if not raw or not raw.endswith(b"\n"):
            raise ValueError("event_source_truncated")
        digest.update(relative.encode("utf-8") + b"\0" + raw + b"\0")
        for line in raw.splitlines():
            try:
                row = json.loads(line)
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValueError("event_row_corrupt") from exc
            if (
                not isinstance(row, dict)
                or set(row) != {"event_id", "session_id", "seq", "type", "ts", "payload"}
                or type(row["seq"]) is not int
                or row["seq"] != len(events) + 1
                or row["session_id"] != session_id
                or not isinstance(row["event_id"], str)
                or not row["event_id"]
                or row["event_id"] in ids
                or not isinstance(row["type"], str)
                or not row["type"]
                or not isinstance(row["ts"], str)
                or not isinstance(row["payload"], dict)
            ):
                raise ValueError("event_identity_or_sequence_invalid")
            ids.add(row["event_id"])
            events.append(Event(**row))
    return events, digest.hexdigest()


def durable_run_admission_verified(
    *,
    event_store: EventStore,
    session_id: str,
    run_generation: str,
    authorization_id: str,
    budget_revision: int | None,
) -> bool:
    """Read-only M5-B presend check: exact fsynced opened/fenced evidence.

    The owning T1 execution still needs its Session run lease and the
    TaskBudgetStore CAS before any external action. This check cannot
    authorize a Run or resolve an unknown Provider/Tool outcome.
    """
    if type(budget_revision) is not int:
        return False
    payload = {
        "schema": SCHEMA,
        "run_generation": run_generation,
        "authorization_id": authorization_id,
        "budget_id": "webt1-" + authorization_id,
        "budget_revision": budget_revision,
    }
    try:
        with event_store._session_flock(session_id, strict=True):  # noqa: SLF001
            events, _ = _strict_snapshot(event_store, session_id)
    except (OSError, ValueError, TypeError, RuntimeError):
        return False
    facts = [
        (i, event) for i, event in enumerate(events)
        if event.type.startswith("run.durable.")
    ]
    return (
        len(facts) == 2
        and facts[0][1].type == OPENED
        and facts[1][1].type == FENCED
        and facts[1][0] == facts[0][0] + 1
        and facts[0][1].payload == payload
        and facts[1][1].payload == payload
    )


def _has_unattributed_pre_run_activity(events: list[Event]) -> bool:
    """Only session creation and user ingress predate a zero-effect M5 Run."""
    return any(
        event.type != "session.created"
        and not (
            event.type == "message.appended"
            and event.payload.get("role") == "user"
        )
        for event in events
    )


def assess_durable_run(
    *,
    event_store: EventStore,
    budget_store: TaskBudgetStore,
    session_id: str,
    run_generation: str,
    authorization_id: str,
) -> RunRecoveryAssessment:
    """Advisory M5 verdict; missing evidence or any external activity means HOLD.

    A positive verdict is limited to an *explicitly fenced, zero-effect* Run.
    Provider/Tool execution remains HOLD until exact settlement and effect
    causation are implemented. A positive verdict never reuses an old Run.
    """
    budget_id = "webt1-" + authorization_id
    base = (session_id, run_generation, authorization_id, budget_id)

    def verdict(
        decision: str, reason: str, *, sha: str = "", revision: int | None = None
    ) -> RunRecoveryAssessment:
        return RunRecoveryAssessment(
            decision, reason, *base, event_snapshot_sha256=sha, budget_revision=revision
        )

    if not all(isinstance(value, str) and value for value in base):
        return verdict(HOLD, "missing_run_identity")
    if not event_store.enabled:
        return verdict(HOLD, "event_store_disabled")
    try:
        first, first_sha = _strict_snapshot(event_store, session_id)
        budget_before = budget_store.read(budget_id)
        second, second_sha = _strict_snapshot(event_store, session_id)
        budget_after = budget_store.read(budget_id)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return verdict(HOLD, "evidence_missing_or_unverifiable")
    if first_sha != second_sha or first != second or budget_before != budget_after:
        return verdict(HOLD, "concurrent_evidence_drift")
    budget = budget_after
    revision = budget.get("revision")
    if type(revision) is not int:
        return verdict(HOLD, "budget_revision_invalid", sha=second_sha)
    evidence = {"sha": second_sha, "revision": revision}

    grant = budget.get("grant") or {}
    member = (budget.get("members") or {}).get(budget_id) or {}
    if (
        grant.get("budget_id") != budget_id
        or grant.get("session_id") != session_id
        or grant.get("profile") != "web-glm-t1-budgeted-write-v1"
        or member.get("session_id") != session_id
        or member.get("run_generation") != run_generation
    ):
        return verdict(HOLD, "budget_identity_mismatch", **evidence)
    # A merely closed_uncertain budget cannot prove a clean zero-effect terminal.
    if budget.get("phase") != "stop_requested":
        return verdict(HOLD, "budget_not_stopped", **evidence)
    if budget.get("reservations"):
        return verdict(HOLD, "external_budget_liability_or_history", **evidence)

    run_events = [
        (i, e) for i, e in enumerate(second)
        if e.type.startswith("run.durable.")
    ]
    if any(e.type not in {OPENED, FENCED, TERMINAL} for _, e in run_events):
        return verdict(HOLD, "unknown_run_protocol_event", **evidence)
    if (
        len(run_events) != 3
        or [e.type for _, e in run_events] != [OPENED, FENCED, TERMINAL]
    ):
        return verdict(HOLD, "durable_run_protocol_incomplete", **evidence)
    (opened_pos, opened), (fenced_pos, fenced), (terminal_pos, terminal) = run_events
    if _has_unattributed_pre_run_activity(second[:opened_pos]):
        return verdict(HOLD, "unattributed_pre_run_activity", **evidence)
    if not opened_pos < fenced_pos < terminal_pos:
        return verdict(HOLD, "durable_run_event_order_invalid", **evidence)
    for _, event in run_events:
        payload = event.payload
        if (
            payload.get("schema") != SCHEMA
            or payload.get("run_generation") != run_generation
            or payload.get("authorization_id") != authorization_id
            or payload.get("budget_id") != budget_id
            or type(payload.get("budget_revision")) is not int
        ):
            return verdict(HOLD, "durable_run_identity_mismatch", **evidence)
    if (
        opened.payload["budget_revision"] > revision
        or fenced.payload["budget_revision"] != opened.payload["budget_revision"]
        or terminal.payload["budget_revision"] != revision
    ):
        return verdict(HOLD, "budget_revision_fence_mismatch", **evidence)

    # Only strict protocol events and a matching run.end may appear after
    # opened. Any Provider/Tool/external/unknown event is an unresolved effect,
    # even when a target file currently matches the expected hash.
    if terminal_pos != len(second) - 1:
        return verdict(HOLD, "events_after_terminal", **evidence)
    middle = second[opened_pos + 1 : terminal_pos]
    if any(e.type not in {FENCED, "run.end"} for e in middle):
        return verdict(HOLD, "external_or_unclassified_activity", **evidence)
    run_ends = [e for e in middle if e.type == "run.end"]
    outcome = terminal.payload.get("outcome")
    end_id = terminal.payload.get("run_end_event_id")
    if outcome == "aborted_before_dispatch":
        if run_ends or end_id != "":
            return verdict(HOLD, "abort_has_ambiguous_terminal", **evidence)
        return verdict(REPLAN, "verified_no_external_dispatch_new_authorization_required", **evidence)
    if outcome == "completed":
        if (
            len(run_ends) != 1
            or run_ends[0].event_id != end_id
            or second.index(run_ends[0]) <= fenced_pos
            or run_ends[0].payload.get("reason") != "completed"
            or run_ends[0].payload.get("run_generation") != run_generation
        ):
            return verdict(HOLD, "completed_terminal_not_correlated", **evidence)
        return verdict(COMPLETED, "verified_zero_effect_run_terminal", **evidence)
    return verdict(HOLD, "unknown_terminal_outcome", **evidence)
