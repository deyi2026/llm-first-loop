"""I0/I1 fail-first contract and persistent CAS tests; no provider/tools/network."""

from __future__ import annotations

import json
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from llm_loop.resources import task_budget_store as disk
from llm_loop.resources.task_budget_contracts import (
    BudgetDimension as D,
)
from llm_loop.resources.task_budget_contracts import (
    BudgetPhase,
    ReservationPhase,
    TaskBudgetCapabilities,
    TaskBudgetGrant,
    TaskBudgetLimits,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_store import (
    TaskBudgetCommitUncertainError,
    TaskBudgetConflictError,
    TaskBudgetCorruptError,
    TaskBudgetDeniedError,
    TaskBudgetPersistError,
    TaskBudgetStore,
)


def _process_attempt(args: tuple[str, int]) -> str:
    """Spawn-safe second process: same CAS revision and durable root."""
    directory, index = args
    store = TaskBudgetStore(directory, clock=lambda: 1000.0)
    root = TaskBudgetMember.from_dict(store.read("root-A")["members"]["root-A"])
    try:
        store.reserve(
            "root-A", member=root, reservation_id=f"process-{index}",
            kind=D.PHYSICAL_ATTEMPTS, expected_revision=2,
        )
        return "won"
    except (TaskBudgetConflictError, TaskBudgetDeniedError):
        return "blocked"


def _grant(
    *,
    capabilities: TaskBudgetCapabilities | None = None,
    limits: TaskBudgetLimits | None = None,
    deadline: float = 5000.0,
) -> TaskBudgetGrant:
    return TaskBudgetGrant(
        budget_id="root-A",
        issuer="test-operator",
        authority_source="offline-test",
        workspace_scope="workspace-A",
        session_id="session-A",
        human_turn_ref="human-turn-A",
        surface="offline_test",
        profile="smoke",
        policy_version="I1-v1",
        deadline_epoch_s=deadline,
        limits=limits or TaskBudgetLimits(
            logical_calls=1,
            physical_attempts=1,
            rounds=1,
            tool_invocations=0,
            input_tokens=2000,
            output_tokens=128,
            payload_bytes=80000,
        ),
        capabilities=capabilities or TaskBudgetCapabilities(),
    )


def _open(
    tmp_path: Path, grant: TaskBudgetGrant | None = None
) -> tuple[TaskBudgetStore, TaskBudgetMember]:
    store = TaskBudgetStore(tmp_path / "budget-state", clock=lambda: 1000.0)
    obj = grant or _grant()
    row = store.issue_root(
        obj, root_run_generation="run-A", ingress_kind="web"
    )
    assert row["phase"] == BudgetPhase.ISSUED
    assert row["revision"] == 1
    assert store.activate(obj.budget_id, expected_revision=1)["revision"] == 2
    return store, TaskBudgetMember.from_dict(store.read(obj.budget_id)["members"][obj.budget_id])


def _reserve(
    store: TaskBudgetStore,
    member: TaskBudgetMember,
    *,
    ident: str = "attempt-1",
    kind: D = D.PHYSICAL_ATTEMPTS,
    measures: dict[D, int] | None = None,
    tool_id: str = "",
    revision: int | None = None,
) -> dict[str, Any]:
    current = store.read("root-A")
    return store.reserve(
        "root-A",
        member=member,
        reservation_id=ident,
        kind=kind,
        expected_revision=current["revision"] if revision is None else revision,
        measures=measures,
        tool_id=tool_id,
    )


def _wake() -> TaskBudgetMember:
    return TaskBudgetMember(
        member_id="wake-A",
        parent_id="root-A",
        workspace_scope="workspace-A",
        session_id="session-A",
        run_generation="run-B",
        ingress_ref="delegated-ingress-A",
        ingress_kind="scheduled:schedule_wake",
        schedule_sid="sched-A",
    )


def test_issue_activate_read_and_never_reissue_to_reset(tmp_path: Path) -> None:
    store, root = _open(tmp_path)
    assert root.ingress_ref == "human-turn-A"
    first = store.read("root-A")
    assert first["grant"]["generation"] == 1
    assert store.issue_root(_grant(), root_run_generation="run-A", ingress_kind="web") == first
    with pytest.raises(TaskBudgetConflictError, match="different identity"):
        store.issue_root(replace(_grant(), session_id="session-B"), root_run_generation="run-A", ingress_kind="web")
    assert store.read("root-A") == first


@pytest.mark.parametrize("invalid", [
    {"physical_attempts": -1},
    {"rounds": True},
    {"input_tokens": 1.5},
])
def test_invalid_limit_types_are_rejected(invalid: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="must be a non-negative"):
        TaskBudgetLimits(**invalid)


def test_unknown_limit_is_not_unlimited(tmp_path: Path) -> None:
    store, root = _open(tmp_path, _grant(limits=TaskBudgetLimits(physical_attempts=None)))
    with pytest.raises(TaskBudgetDeniedError, match="dimension_unqualified"):
        _reserve(store, root)
    assert store.report("root-A")["used_or_reserved"][D.PHYSICAL_ATTEMPTS.value] == 0


def test_explicit_empty_tools_deny_and_capability_distinction(tmp_path: Path) -> None:
    store, root = _open(tmp_path)
    with pytest.raises(TaskBudgetDeniedError, match="tool_not_allowed"):
        _reserve(store, root, kind=D.TOOL_INVOCATIONS, tool_id="schedule")
    assert TaskBudgetCapabilities(allowed_tools=None).allowed_tools is None
    assert TaskBudgetCapabilities().allowed_tools == frozenset()


def test_atomic_reservation_covers_measures_and_denies_second_physical_attempt(tmp_path: Path) -> None:
    store, root = _open(tmp_path)
    first = _reserve(
        store, root, measures={D.INPUT_TOKENS: 1100, D.OUTPUT_TOKENS: 60, D.PAYLOAD_BYTES: 900},
    )
    assert first["revision"] == 3
    with pytest.raises(TaskBudgetDeniedError, match="budget_exhausted:physical_attempts"):
        _reserve(store, root, ident="attempt-2")
    assert store.report("root-A")["used_or_reserved"][D.INPUT_TOKENS.value] == 1100
    assert store.read("root-A")["revision"] == 3


def test_exact_reservation_retries_are_idempotent_and_payload_drift_conflicts(tmp_path: Path) -> None:
    store, root = _open(tmp_path)
    result = _reserve(store, root)
    assert _reserve(store, root) == result
    with pytest.raises(TaskBudgetConflictError, match="changed request"):
        _reserve(store, root, measures={D.INPUT_TOKENS: 1})
    assert store.report("root-A")["used_or_reserved"][D.PHYSICAL_ATTEMPTS.value] == 1


def test_generation_revision_cas_prevents_lost_concurrent_reservations(tmp_path: Path) -> None:
    store, root = _open(
        tmp_path, _grant(limits=TaskBudgetLimits(physical_attempts=1)),
    )

    def compete(i: int) -> str:
        client = TaskBudgetStore(store.directory, clock=lambda: 1000.0)
        try:
            client.reserve(
                "root-A", member=root, reservation_id=f"retry-{i}",
                kind=D.PHYSICAL_ATTEMPTS, expected_revision=2,
            )
            return "winner"
        except (TaskBudgetConflictError, TaskBudgetDeniedError):
            return "blocked"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(compete, range(8)))
    assert outcomes.count("winner") == 1
    assert outcomes.count("blocked") == 7
    assert store.read("root-A")["revision"] == 3
    assert len(store.read("root-A")["reservations"]) == 1


def test_cross_instance_stale_writer_must_refresh(tmp_path: Path) -> None:
    store, root = _open(tmp_path)
    other = TaskBudgetStore(store.directory, clock=lambda: 1000.0)
    before = other.read("root-A")["revision"]
    _reserve(store, root)
    with pytest.raises(TaskBudgetConflictError, match="stale"):
        other.reserve("root-A", member=root, reservation_id="attempt-2", kind=D.PHYSICAL_ATTEMPTS, expected_revision=before)
    assert len(other.read("root-A")["reservations"]) == 1


def test_separate_processes_share_same_physical_budget_cas(tmp_path: Path) -> None:
    store, _root = _open(tmp_path)
    directory = str(store.directory)
    with ProcessPoolExecutor(
        max_workers=3, mp_context=multiprocessing.get_context("spawn")
    ) as executor:
        outcomes = list(executor.map(_process_attempt, [(directory, n) for n in range(3)]))
    assert outcomes.count("won") == 1
    assert outcomes.count("blocked") == 2
    assert len(TaskBudgetStore(directory).read("root-A")["reservations"]) == 1


def test_wake_inherits_root_balance_after_restart(tmp_path: Path) -> None:
    grant = _grant(capabilities=TaskBudgetCapabilities(allow_wake=True))
    store, root = _open(tmp_path, grant)
    member = _wake()
    stored = store.bind_member("root-A", member, expected_revision=2)
    assert stored["revision"] == 3
    # Repeated same wake identity cannot mint budget or duplicate a member.
    assert store.bind_member("root-A", member, expected_revision=3)["revision"] == 3
    _reserve(store, root, ident="attempt-A")
    restarted = TaskBudgetStore(store.directory, clock=lambda: 1000.0)
    with pytest.raises(TaskBudgetDeniedError, match="budget_exhausted"):
        _reserve(restarted, member, ident="attempt-B")
    report = restarted.report("root-A")
    assert report["used_or_reserved"][D.PHYSICAL_ATTEMPTS.value] == 1
    assert len(restarted.read("root-A")["members"]) == 2


def test_wake_must_have_bound_parent_and_explicit_capability(tmp_path: Path) -> None:
    store, _root = _open(tmp_path)
    with pytest.raises(TaskBudgetDeniedError, match="wake_not_allowed"):
        store.bind_member("root-A", _wake(), expected_revision=2)
    with pytest.raises(TaskBudgetDeniedError, match="member_identity_mismatch"):
        _reserve(store, _wake())
    assert store.read("root-A")["members"].keys() == {"root-A"}


def test_child_cannot_cross_workspace_session_or_rebind_identity(tmp_path: Path) -> None:
    store, _ = _open(tmp_path, _grant(capabilities=TaskBudgetCapabilities(allow_wake=True)))
    with pytest.raises(TaskBudgetDeniedError, match="scope_mismatch"):
        store.bind_member("root-A", replace(_wake(), session_id="session-other"), expected_revision=2)
    with pytest.raises(TaskBudgetDeniedError, match="unknown_parent"):
        store.bind_member("root-A", replace(_wake(), parent_id="not-member"), expected_revision=2)
    store.bind_member("root-A", _wake(), expected_revision=2)
    with pytest.raises(TaskBudgetConflictError, match="different authority"):
        store.bind_member("root-A", replace(_wake(), run_generation="run-new"), expected_revision=3)


def test_pre_transport_abort_is_only_reclaimable_allocation(tmp_path: Path) -> None:
    store, root = _open(tmp_path)
    row = _reserve(store, root)
    aborted = store.abort_before_dispatch(
        "root-A", "attempt-1", expected_revision=row["revision"], proof_ref="proof-unsent",
    )
    assert aborted["reservations"]["attempt-1"]["phase"] == ReservationPhase.ABORTED_BEFORE_DISPATCH
    assert store.report("root-A")["used_or_reserved"][D.PHYSICAL_ATTEMPTS.value] == 0
    _reserve(store, root, ident="attempt-2")
    with pytest.raises(TaskBudgetConflictError, match="evidence changed"):
        store.abort_before_dispatch(
            "root-A", "attempt-1",
            expected_revision=store.read("root-A")["revision"],
            proof_ref="different-proof",
        )


def test_dispatched_failure_still_consumes_attempt_and_never_refunds(tmp_path: Path) -> None:
    store, root = _open(tmp_path)
    row = _reserve(store, root)
    dispatched = store.mark_dispatched("root-A", "attempt-1", expected_revision=row["revision"])
    with pytest.raises(TaskBudgetDeniedError, match="cannot_refund"):
        store.abort_before_dispatch(
            "root-A", "attempt-1", expected_revision=dispatched["revision"],
            proof_ref="not-real-proof",
        )
    settled = store.settle(
        "root-A", "attempt-1", expected_revision=dispatched["revision"],
        receipt_ref="settled-1", outcome="failure", usage_complete=True,
    )
    assert settled["reservations"]["attempt-1"]["phase"] == ReservationPhase.SETTLED
    assert store.report("root-A")["used_or_reserved"][D.PHYSICAL_ATTEMPTS.value] == 1


def test_unknown_usage_keeps_liability_and_never_closes_verified(tmp_path: Path) -> None:
    store, root = _open(tmp_path)
    row = _reserve(store, root)
    dispatched = store.mark_dispatched("root-A", "attempt-1", expected_revision=row["revision"])
    unknown = store.settle(
        "root-A", "attempt-1", expected_revision=dispatched["revision"],
        receipt_ref="transport-incomplete", outcome="interrupted", usage_complete=False,
    )
    assert unknown["reservations"]["attempt-1"]["phase"] == ReservationPhase.UNKNOWN
    report = store.report("root-A")
    assert report["outstanding_or_unknown"] == ["attempt-1"]
    assert report["physical_quiescence_verified"] is False
    stopped = store.request_stop("root-A", expected_revision=unknown["revision"], reason="owner_stop")
    settling = store.mark_settling("root-A", expected_revision=stopped["revision"])
    closed = store.close_uncertain("root-A", expected_revision=settling["revision"])
    assert closed["phase"] == BudgetPhase.CLOSED_UNCERTAIN
    assert "closed_verified" not in [p.value for p in BudgetPhase]


def test_stop_or_deadline_blocks_new_reserve_and_reserved_dispatch(tmp_path: Path) -> None:
    store, root = _open(tmp_path)
    reserved = _reserve(store, root)
    stopped = store.request_stop("root-A", expected_revision=reserved["revision"], reason="stop")
    assert stopped["phase"] == BudgetPhase.STOP_REQUESTED
    with pytest.raises(TaskBudgetDeniedError, match="budget_not_active"):
        _reserve(store, root, ident="another")
    with pytest.raises(TaskBudgetDeniedError, match="dispatch_forbidden"):
        store.mark_dispatched("root-A", "attempt-1", expected_revision=stopped["revision"])
    expired = TaskBudgetStore(tmp_path / "expired", clock=lambda: 8000.0)
    expired.issue_root(_grant(), root_run_generation="run-A", ingress_kind="web")
    with pytest.raises(TaskBudgetDeniedError, match="deadline_expired"):
        expired.activate("root-A", expected_revision=1)


def test_deadline_becomes_effective_on_every_new_reservation_and_child(tmp_path: Path) -> None:
    now = [1000.0]
    grant = _grant(capabilities=TaskBudgetCapabilities(allow_wake=True))
    store = TaskBudgetStore(tmp_path / "clock-state", clock=lambda: now[0])
    store.issue_root(grant, root_run_generation="run-A", ingress_kind="web")
    store.activate("root-A", expected_revision=1)
    now[0] = 5000.0
    with pytest.raises(TaskBudgetDeniedError, match="deadline_expired"):
        store.bind_member("root-A", _wake(), expected_revision=2)
    root = TaskBudgetMember.from_dict(store.read("root-A")["members"]["root-A"])
    with pytest.raises(TaskBudgetDeniedError, match="deadline_expired"):
        _reserve(store, root)


def test_measurements_never_use_implicit_token_zero_or_exactness(tmp_path: Path) -> None:
    grant = _grant(limits=TaskBudgetLimits(
        physical_attempts=2, input_tokens=3, payload_bytes=100
    ))
    store, root = _open(tmp_path, grant)
    _reserve(store, root, measures={D.INPUT_TOKENS: 3})
    with pytest.raises(TaskBudgetDeniedError, match="budget_exhausted:input_tokens"):
        _reserve(store, root, ident="attempt-2", measures={D.INPUT_TOKENS: 1})
    with pytest.raises(TaskBudgetDeniedError, match="dimension_unqualified:output_tokens"):
        _reserve(store, root, ident="attempt-3", measures={D.OUTPUT_TOKENS: 1})
    assert store.report("root-A")["used_or_reserved"][D.INPUT_TOKENS.value] == 3


def test_tighten_cannot_expand_tools_budget_wake_or_deadline(tmp_path: Path) -> None:
    start = _grant(capabilities=TaskBudgetCapabilities(
        allowed_tools=frozenset({"read_file", "schedule"}), allow_wake=True
    ), limits=TaskBudgetLimits(logical_calls=3, physical_attempts=3, tool_invocations=3))
    store, _ = _open(tmp_path, start)
    tighter = TaskBudgetLimits(logical_calls=2, physical_attempts=1, tool_invocations=0)
    cap = TaskBudgetCapabilities(allowed_tools=frozenset(), allow_wake=False)
    row = store.tighten(
        "root-A", expected_revision=2, expected_generation=1,
        limits=tighter, capabilities=cap, deadline_epoch_s=4000.0,
    )
    assert row["grant"]["generation"] == 2
    with pytest.raises(TaskBudgetDeniedError, match="policy_relaxation"):
        store.tighten(
            "root-A", expected_revision=3, expected_generation=2,
            limits=start.limits, capabilities=start.capabilities,
            deadline_epoch_s=5000.0,
        )
    with pytest.raises(TaskBudgetConflictError, match="generation"):
        store.tighten(
            "root-A", expected_revision=3, expected_generation=1,
            limits=tighter, capabilities=cap, deadline_epoch_s=3500.0,
        )
    with pytest.raises(TaskBudgetDeniedError, match="wake_not_allowed"):
        store.bind_member("root-A", _wake(), expected_revision=3)


def test_pending_work_from_old_policy_generation_cannot_dispatch_after_tighten(
    tmp_path: Path,
) -> None:
    start = _grant(
        limits=TaskBudgetLimits(physical_attempts=2),
        capabilities=TaskBudgetCapabilities(),
    )
    store, root = _open(tmp_path, start)
    reserved = _reserve(store, root, ident="pending-1")
    assert reserved["reservations"]["pending-1"]["policy_generation"] == 1
    tightened = store.tighten(
        "root-A",
        expected_revision=reserved["revision"],
        expected_generation=1,
        limits=TaskBudgetLimits(physical_attempts=0),
        capabilities=TaskBudgetCapabilities(),
        deadline_epoch_s=4000.0,
    )
    assert tightened["grant"]["generation"] == 2
    assert store.report("root-A")["over_limit_dimensions"] == [
        D.PHYSICAL_ATTEMPTS.value
    ]
    with pytest.raises(TaskBudgetDeniedError, match="policy_change"):
        store.mark_dispatched(
            "root-A", "pending-1", expected_revision=tightened["revision"]
        )
    # Stale retry reconciles its existing reservation and cannot create a new one.
    assert _reserve(store, root, ident="pending-1")["revision"] == tightened["revision"]
    with pytest.raises(TaskBudgetDeniedError, match="budget_exhausted"):
        _reserve(store, root, ident="pending-2")
    assert store.read("root-A")["reservations"]["pending-1"]["phase"] == ReservationPhase.RESERVED


def test_corrupt_state_never_becomes_empty_balance(tmp_path: Path) -> None:
    store, root = _open(tmp_path)
    _reserve(store, root)
    path, _lock = store._paths("root-A")
    path.write_text("{bad JSON")
    with pytest.raises(TaskBudgetCorruptError):
        store.read("root-A")
    with pytest.raises(TaskBudgetCorruptError):
        _reserve(store, root, ident="attempt-new")
    with pytest.raises(TaskBudgetCorruptError):
        store.issue_root(_grant(), root_run_generation="run-A", ingress_kind="web")
    assert path.read_text() == "{bad JSON"


def test_structured_corruption_is_rejected_without_repair_reset(tmp_path: Path) -> None:
    store, root = _open(tmp_path)
    _reserve(store, root)
    path, _ = store._paths("root-A")
    row = json.loads(path.read_text())
    row["reservations"]["attempt-1"]["kind"] = D.OUTPUT_TOKENS.value
    path.write_text(json.dumps(row))
    with pytest.raises(TaskBudgetCorruptError):
        store.read("root-A")
    with pytest.raises(TaskBudgetCorruptError):
        _reserve(store, root, ident="forged-next")


def test_symlink_snapshot_is_not_trusted_as_authority(tmp_path: Path) -> None:
    store, root = _open(tmp_path)
    path, _ = store._paths("root-A")
    alternate = tmp_path / "alternate.json"
    alternate.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(alternate)
    with pytest.raises(TaskBudgetCorruptError):
        store.read("root-A")
    with pytest.raises(TaskBudgetCorruptError):
        _reserve(store, root)


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="POSIX no-follow lock primitive")
def test_symlink_lock_is_refused(tmp_path: Path) -> None:
    store, _ = _open(tmp_path)
    _, lock = store._paths("root-A")
    attacker = tmp_path / "outside"
    attacker.write_text("unmodified")
    lock.unlink()
    lock.symlink_to(attacker)
    with pytest.raises(TaskBudgetPersistError):
        store.activate("root-A", expected_revision=2)
    assert attacker.read_text() == "unmodified"


def test_traversal_and_schema_forgery_fail_closed(tmp_path: Path) -> None:
    store = TaskBudgetStore(tmp_path / "state")
    with pytest.raises(ValueError):
        store.read("../../etc/passwd")
    store, _ = _open(tmp_path)
    path, _ = store._paths("root-A")
    data = json.loads(path.read_text())
    data["schema"] = "unknown-version"
    path.write_text(json.dumps(data))
    with pytest.raises(TaskBudgetCorruptError):
        store.read("root-A")


def test_torn_temp_or_pre_replace_failure_preserves_existing_snapshot(tmp_path: Path, monkeypatch: Any) -> None:
    store, root = _open(tmp_path)
    old = store.read("root-A")
    path, _ = store._paths("root-A")
    original = disk._write_temp_exclusive

    def torn(temp: Path, payload: bytes) -> None:
        temp.write_bytes(payload[:len(payload) // 2])
        raise OSError(28, "disk full")

    monkeypatch.setattr(disk, "_write_temp_exclusive", torn)
    with pytest.raises(TaskBudgetPersistError) as caught:
        _reserve(store, root)
    assert caught.value.retry_safe is True
    assert store.read("root-A") == old
    assert not list(path.parent.glob(path.name + ".*.tmp"))
    monkeypatch.setattr(disk, "_write_temp_exclusive", original)


def test_first_use_root_directory_fsync_failure_prevents_issuance(
    tmp_path: Path, monkeypatch: Any
) -> None:
    parent = tmp_path / "new-budget-root"
    store = TaskBudgetStore(parent)
    original = disk._fsync_directory

    def fail_parent_sync(directory: Path) -> None:
        if Path(directory) == tmp_path:
            raise OSError(5, "parent directory not durable")
        original(directory)

    monkeypatch.setattr(disk, "_fsync_directory", fail_parent_sync)
    with pytest.raises(TaskBudgetPersistError):
        store.issue_root(_grant(), root_run_generation="run-A", ingress_kind="web")
    path, _ = store._paths("root-A")
    assert not path.exists()
    monkeypatch.setattr(disk, "_fsync_directory", original)
    assert store.issue_root(
        _grant(), root_run_generation="run-A", ingress_kind="web"
    )["revision"] == 1


def test_replace_failure_does_not_mutate_root(tmp_path: Path, monkeypatch: Any) -> None:
    store, root = _open(tmp_path)
    old = store.read("root-A")
    path, _ = store._paths("root-A")
    original = disk.os.replace

    def fail_replace(src: Path, dst: Path) -> None:
        if Path(dst) == path:
            raise OSError(5, "replace failed")
        original(src, dst)

    monkeypatch.setattr(disk.os, "replace", fail_replace)
    with pytest.raises(TaskBudgetPersistError) as caught:
        _reserve(store, root)
    assert caught.value.retry_safe is True
    assert store.read("root-A") == old
    assert not list(path.parent.glob(path.name + ".*.tmp"))


def test_post_replace_dirfsync_failure_is_uncertain_and_no_double_charge(tmp_path: Path, monkeypatch: Any) -> None:
    store, root = _open(tmp_path)
    path, _ = store._paths("root-A")
    original = disk._fsync_directory
    calls = 0

    def always_fail(directory: Path) -> None:
        nonlocal calls
        if Path(directory) == path.parent:
            calls += 1
            raise OSError(5, "directory fsync unavailable")
        return original(directory)

    monkeypatch.setattr(disk, "_fsync_directory", always_fail)
    with pytest.raises(TaskBudgetCommitUncertainError) as caught:
        _reserve(store, root, ident="attempt-1")
    assert calls == disk._DIR_FSYNC_ATTEMPTS
    assert caught.value.retry_safe is False
    assert caught.value.visible_state == "matches"
    reloaded = TaskBudgetStore(store.directory, clock=lambda: 1000.0)
    assert reloaded.read("root-A")["revision"] == 3
    monkeypatch.setattr(disk, "_fsync_directory", original)
    assert _reserve(reloaded, root, ident="attempt-1")["revision"] == 3
    assert reloaded.report("root-A")["used_or_reserved"][D.PHYSICAL_ATTEMPTS.value] == 1


def test_transient_directory_fsync_failure_is_retried_without_rewriting(
    tmp_path: Path, monkeypatch: Any
) -> None:
    store, root = _open(tmp_path)
    original_sync = disk._fsync_directory
    original_replace = disk.os.replace
    events = {"fsync": 0, "replace": 0}

    def flaky_sync(directory: Path) -> None:
        if Path(directory) == store.directory:
            events["fsync"] += 1
            if events["fsync"] == 1:
                raise OSError(5, "transient metadata error")
        original_sync(directory)

    def count_replace(source: Path, target: Path) -> None:
        events["replace"] += 1
        original_replace(source, target)

    monkeypatch.setattr(disk, "_fsync_directory", flaky_sync)
    monkeypatch.setattr(disk.os, "replace", count_replace)
    assert _reserve(store, root)["revision"] == 3
    assert events == {"fsync": 2, "replace": 1}


def test_no_external_result_can_mark_physical_closure_verified(tmp_path: Path) -> None:
    store, root = _open(tmp_path)
    reservation = _reserve(store, root)
    dispatched = store.mark_dispatched("root-A", "attempt-1", expected_revision=reservation["revision"])
    assert store.mark_dispatched("root-A", "attempt-1", expected_revision=dispatched["revision"])["revision"] == dispatched["revision"]
    settled = store.settle(
        "root-A", "attempt-1", expected_revision=dispatched["revision"],
        receipt_ref="receipt-1", outcome="success", usage_complete=True,
    )
    assert store.settle(
        "root-A", "attempt-1", expected_revision=settled["revision"],
        receipt_ref="receipt-1", outcome="success", usage_complete=True,
    )["revision"] == settled["revision"]
    stopped = store.request_stop("root-A", expected_revision=settled["revision"], reason="complete")
    settling = store.mark_settling("root-A", expected_revision=stopped["revision"])
    final = store.close_uncertain("root-A", expected_revision=settling["revision"])
    assert final["phase"] == BudgetPhase.CLOSED_UNCERTAIN
    assert store.report("root-A")["outstanding_or_unknown"] == []
    assert store.report("root-A")["physical_quiescence_verified"] is False


def test_snapshot_copy_cannot_write_authority(tmp_path: Path) -> None:
    store, _ = _open(tmp_path)
    snapshot = store.read("root-A")
    snapshot["grant"]["limits"]["physical_attempts"] = 999_999
    assert store.read("root-A")["grant"]["limits"]["physical_attempts"] == 1


def test_files_mode_private_and_only_identity_facts_persist(tmp_path: Path) -> None:
    store, root = _open(tmp_path)
    _reserve(store, root)
    path, lock = store._paths("root-A")
    assert path.stat().st_mode & 0o777 == 0o600
    assert lock.stat().st_mode & 0o777 == 0o600
    contents = path.read_text()
    assert "LLM_API_KEY" not in contents and "prompt_content" not in contents
    assert "root-A" in contents and "human-turn-A" in contents
