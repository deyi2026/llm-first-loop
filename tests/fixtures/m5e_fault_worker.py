"""Offline-only M5-E child: deterministic real SIGKILL and two-worker probes.

This is NOT a Provider or Tool dispatcher. It never makes network requests,
retries a Run, or touches any path outside its pytest tmp_path.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from llm_loop.core.durable_run_recovery import FENCED, OPENED, SCHEMA, TERMINAL
from llm_loop.core.session import SessionStore
from llm_loop.core.trace_leak.ingress_token import issue_ingress
from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_contracts import BudgetDimension, TaskBudgetMember
from llm_loop.resources.task_budget_dispatch import exact_workspace_scope
from llm_loop.resources.task_budget_store import TaskBudgetStore
from llm_loop.resources.task_budget_t1_web_profile import (
    T1WebBudgetExecution,
    T1WebEventPlan,
    prepare_t1_web_event_budget,
)
from llm_loop.workspace.file_service import FileService

root = Path(sys.argv[2]).resolve()
mode = sys.argv[1]
stage = sys.argv[3]
marker = Path(sys.argv[4]).resolve()
release = Path(sys.argv[5]).resolve() if len(sys.argv) > 5 else None
config = json.loads((root / "plan.json").read_text(encoding="utf-8"))
sid = config["session_id"]
auth = config["authorization_id"]
generation = config["run_generation"]
bid = "webt1-" + auth
events = EventStore(root / "events")
budget = TaskBudgetStore(root / "ledger")


def reached(label: str, *, pause: bool = True) -> None:
    with open(marker, "x", encoding="utf-8") as stream:
        stream.write(label)
        stream.flush()
        os.fsync(stream.fileno())
    if pause:
        signal.pause()


def await_release() -> None:
    if release is None:
        raise RuntimeError("release marker required")
    deadline = time.monotonic() + 12
    while not release.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("test barrier timeout")
        time.sleep(0.01)


def result(value: dict[str, Any]) -> None:
    (marker.parent / (marker.name + ".result")).write_text(
        json.dumps(value, sort_keys=True), encoding="utf-8"
    )


def plan() -> T1WebEventPlan:
    return T1WebEventPlan(
        session_id=sid,
        workspace_scope=exact_workspace_scope(str(root)),
        authorization_id=auth,
        target_path="docs/target.md",
        prepared_target_sha256=config["target_sha256"],
        valid_from_epoch_s=config["valid_from_epoch_s"],
        valid_until_epoch_s=config["valid_until_epoch_s"],
        event_store=events,
        budget_store=budget,
        durable_run_admission_required=True,
        operator_config_path=config.get("operator_config_path", ""),
        operator_config_sha256=config.get("operator_config_sha256", ""),
    )


def prepare() -> T1WebBudgetExecution:
    event = next(e for e in events.read(sid) if e.type == "message.appended")
    execution = prepare_t1_web_event_budget(
        plan=plan(),
        event=event,
        session_id=sid,
        workspace_root=str(root),
        run_generation=generation,
        user_text=config["user_text"],
        ingress=issue_ingress("web"),
    )
    if not isinstance(execution, T1WebBudgetExecution):
        raise RuntimeError("wrong execution type")
    return execution


def rebind() -> T1WebBudgetExecution:
    """Test-only reconstruction; never grant admission based on this object."""
    row = budget.read(bid)
    member = TaskBudgetMember.from_dict(row["members"][bid])
    execution = T1WebBudgetExecution(store=budget, budget_id=bid, member=member)
    execution._t1_plan = plan()
    execution._t1_event_store = events
    execution._t1_workspace_root = str(root)
    execution._t1_target_path = "docs/target.md"
    execution._t1_target_sha = config["target_sha256"]
    execution._t1_durable_run_fenced = True
    execution._t1_durable_admission_revision = config["admission_revision"]
    return execution


def admission() -> None:
    real = events.append_durable_run_fact

    def intercepted(session_id: str, event_type: str, payload: dict):
        if stage == "before_open" and event_type == OPENED:
            reached(stage)
        event = real(session_id, event_type, payload)
        if stage == "after_open" and event_type == OPENED:
            reached(stage)
        if stage == "after_fence" and event_type == FENCED:
            reached(stage)
        return event

    events.append_durable_run_fact = intercepted
    prepare()
    raise RuntimeError("admission crash barrier not reached")


def provider() -> None:
    execution = rebind()
    execution.note_prepared_request({
        "projected_bytes": 1000, "controls": {"max_tokens": 128},
    })
    if stage in {"before_dispatch", "after_dispatch"}:
        real = budget.mark_dispatched

        def intercepted(budget_id: str, reservation_id: str, *, expected_revision: int):
            if stage == "before_dispatch":
                reached(stage)
            row = real(
                budget_id, reservation_id, expected_revision=expected_revision
            )
            reached(stage)
            return row

        budget.mark_dispatched = intercepted
    execution.reserve(BudgetDimension.PHYSICAL_ATTEMPTS)
    if stage in {"before_dispatch", "after_dispatch"}:
        raise RuntimeError("provider dispatch crash barrier not reached")
    call = "pcall:" + "c" * 32
    attempt = "pattempt:" + "d" * 32
    events.append(sid, "provider.call.opened", {
        "call_id": call, "origin_run_generation": generation,
    })
    events.append(sid, "provider.transport.opened", {
        "call_id": call, "attempt_id": attempt,
    })
    if stage == "transport_opened":
        reached(stage)
    events.append(sid, "provider.transport.settled", {
        "call_id": call, "attempt_id": attempt, "outcome": "success",
    })
    if stage == "transport_settled":
        reached(stage)
    raise RuntimeError("provider crash barrier not reached")


class EffectSink:
    workspace_scope = str(root)
    owner_session_id = sid
    operation_id = "m5e-tool"
    tool_call_id = "m5e-call"
    tool_name = "edit_file"
    effect_kind = "file_edit"
    records_durable = False

    @contextmanager
    def mutation_authority(self):
        yield True

    def prepared(
        self, *, canonical_path: Path, before_bytes: bytes,
        expected_after_bytes: bytes,
    ) -> bool:
        events.append(sid, "tool.execution.effect_prepared", {
            "execution_id": "m5e-tool",
            "origin_run_generation": generation,
            "canonical_path": str(canonical_path),
            "before_sha256": hashlib.sha256(before_bytes).hexdigest(),
            "expected_after_sha256": hashlib.sha256(expected_after_bytes).hexdigest(),
        })
        if stage == "effect_prepared":
            reached(stage)
        return True

    def observed(
        self, *, canonical_path: Path, actual_after_bytes: bytes,
        expected_after_bytes: bytes, actual_mtime_ns: int | None, artifact_ref: str,
    ) -> bool:
        events.append(sid, "tool.execution.effect_observed", {
            "execution_id": "m5e-tool",
            "origin_run_generation": generation,
            "canonical_path": str(canonical_path),
            "actual_after_sha256": hashlib.sha256(actual_after_bytes).hexdigest(),
            "matches_expected": actual_after_bytes == expected_after_bytes,
        })
        if stage == "effect_observed":
            reached(stage)
        return True


def tool() -> None:
    row = budget.read(bid)
    member = TaskBudgetMember.from_dict(row["members"][bid])
    rid = "dispatch-m5e-tool"
    row = budget.reserve(
        bid, member=member, reservation_id=rid,
        kind=BudgetDimension.TOOL_INVOCATIONS,
        tool_id="edit_file", expected_revision=row["revision"],
    )
    budget.mark_dispatched(bid, rid, expected_revision=row["revision"])
    target = root / "docs" / "target.md"
    if stage == "effect_replaced":
        import llm_loop.workspace.file_service as module

        real_replace = module.os.replace

        def intercepted(src: Any, dst: Any) -> None:
            real_replace(src, dst)
            if Path(dst).resolve() == target.resolve():
                reached(stage)

        module.os.replace = intercepted
    FileService(lock_root=root / "file_locks").edit(
        path=target,
        old_string="OLD",
        new_string="NEW",
        workspace_scope=str(root),
        effect_sink=EffectSink(),
    )
    raise RuntimeError("tool crash barrier not reached")


def finalizer() -> None:
    row = budget.read(bid)
    row = budget.request_stop(
        bid, expected_revision=row["revision"], reason="offline_finalizer"
    )
    end = events.append(sid, "run.end", {
        "reason": "completed", "run_generation": generation,
    })
    if end is None:
        raise RuntimeError("synthetic run.end append failed")
    if stage == "after_run_end":
        reached(stage)
    events.append_durable_run_fact(sid, TERMINAL, {
        "schema": SCHEMA,
        "run_generation": generation,
        "authorization_id": auth,
        "budget_id": bid,
        "budget_revision": row["revision"],
        "outcome": "completed",
        "run_end_event_id": end.event_id,
    })
    if stage == "after_terminal":
        reached(stage)
    raise RuntimeError("finalizer crash barrier not reached")


def lease() -> None:
    session = SessionStore(root / "sessions")
    with session.run_lease(sid) as acquired:
        if mode == "lease_probe":
            result({"acquired": acquired})
            return
        if not acquired:
            raise RuntimeError("owner lease not acquired")
        reached(stage)


def cas() -> None:
    row = budget.read(bid)
    member = TaskBudgetMember.from_dict(row["members"][bid])
    reached("ready", pause=False)
    await_release()
    try:
        updated = budget.reserve(
            bid, member=member, reservation_id="dispatch-" + stage,
            kind=BudgetDimension.PHYSICAL_ATTEMPTS,
            expected_revision=row["revision"],
        )
    except Exception as exc:
        result({"outcome": "denied", "exception": type(exc).__name__})
    else:
        result({"outcome": "reserved", "revision": updated["revision"]})


def replay_probe() -> None:
    execution = rebind()
    try:
        execution.reserve(BudgetDimension.TOOL_INVOCATIONS, tool_id="read_file")
    except Exception as exc:
        result({"outcome": "denied", "exception": type(exc).__name__})
    else:
        result({"outcome": "unexpectedly_allowed"})


def revoke() -> None:
    execution = rebind()
    reached("ready", pause=False)
    await_release()
    try:
        execution.reserve(BudgetDimension.TOOL_INVOCATIONS, tool_id="read_file")
    except Exception as exc:
        result({"outcome": "denied", "exception": type(exc).__name__})
    else:
        result({"outcome": "unexpectedly_allowed"})


if __name__ == "__main__":
    actions = {
        "admission": admission,
        "provider": provider,
        "tool": tool,
        "finalizer": finalizer,
        "lease_hold": lease,
        "lease_probe": lease,
        "budget_cas": cas,
        "revoke": revoke,
        "replay_probe": replay_probe,
    }
    actions[mode]()
