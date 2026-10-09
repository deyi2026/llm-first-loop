"""I2/I3 opt-in physical dispatch gates, deliberately without a live issuer.

Only a programmatic, explicitly bound TaskBudgetExecution can activate this
gate. No production ingress, config value, scheduler or provider currently
binds it, so normal LFL work is unchanged. The gate is fail-closed for a bound
root and uses the I1 store, not an in-memory counter or RG-3D projection.

Transport reservations mean *attempted send*, not exact GLM usage/billing.
Tool settlement means the Registry returned, not that external side effects
are rollbackable or quiescence has been independently verified.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llm_loop.resources.task_budget_contracts import (
    BudgetDimension,
    BudgetPhase,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_store import (
    TaskBudgetConflictError,
    TaskBudgetDeniedError,
    TaskBudgetStore,
    _finite_time,
)

_MAX_CAS_RETRIES = 12


def exact_workspace_scope(workspace_root: str) -> str:
    """Opaque canonical workspace identity; no path serialized to ledger."""
    return "ws-" + hashlib.sha256(
        str(Path(workspace_root).expanduser().resolve()).encode()
    ).hexdigest()[:32]


@dataclass(frozen=True)
class TaskBudgetExecution:
    store: TaskBudgetStore
    budget_id: str
    member: TaskBudgetMember
    _local_stop: threading.Event = field(
        default_factory=threading.Event, repr=False, compare=False
    )

    def _get_validated(self) -> dict[str, Any]:
        if self._local_stop.is_set():
            raise TaskBudgetDeniedError("local_run_stop_requested")
        snapshot = self.store.read(self.budget_id)
        if snapshot["phase"] != BudgetPhase.ACTIVE:
            raise TaskBudgetDeniedError("budget_not_active")
        if snapshot["members"].get(self.member.member_id) != self.member.to_dict():
            raise TaskBudgetDeniedError("member_identity_mismatch")
        if _finite_time(self.store._clock()) >= snapshot["grant"]["deadline_epoch_s"]:
            raise TaskBudgetDeniedError("deadline_expired")
        from llm_loop.core.run_context import (
            current_run_generation,
            current_session_id,
            current_workspace_root,
        )

        # The I2/I3 context is an offline attachment, not a signed ingress
        # grant. Nevertheless, any ambient real Run binding must agree with
        # its declared owner rather than borrow a different session's quota.
        if current_session_id.get() and current_session_id.get() != self.member.session_id:
            raise TaskBudgetDeniedError("active_session_scope_mismatch")
        if (
            current_run_generation.get()
            and current_run_generation.get() != self.member.run_generation
        ):
            raise TaskBudgetDeniedError("active_run_generation_mismatch")
        if (
            current_workspace_root.get()
            and current_workspace_root.get() != self.member.workspace_scope
            and exact_workspace_scope(current_workspace_root.get()) != self.member.workspace_scope
        ):
            raise TaskBudgetDeniedError("active_workspace_scope_mismatch")
        return snapshot

    def assert_tool_allowed(self, name: str) -> None:
        snapshot = self._get_validated()
        allowed = snapshot["grant"]["capabilities"]["allowed_tools"]
        if allowed is not None and name not in allowed:
            raise TaskBudgetDeniedError("tool_not_allowed")
        if snapshot["grant"]["limits"]["tool_invocations"] == 0:
            raise TaskBudgetDeniedError("tool_budget_exhausted")
        if name in {
            "schedule", "schedule_cancel", "execute_command", "spawn_subagent"
        }:
            # Neither the wake lineage recovery path nor shell/subagent child
            # process cleanup is bound to this new budget in I2/I3. Even an
            # allowlist entry does not make those effects safe yet.
            raise TaskBudgetDeniedError("derived_execution_capability_unqualified")

    def _cas_mutate(self, method: str, **kwargs: Any) -> dict[str, Any]:
        for _ in range(_MAX_CAS_RETRIES):
            current = self.store.read(self.budget_id)
            try:
                return getattr(self.store, method)(
                    self.budget_id,
                    expected_revision=current["revision"],
                    **kwargs,
                )
            except TaskBudgetConflictError as exc:
                if "stale budget revision CAS" not in str(exc):
                    raise
        raise TaskBudgetDeniedError("cas_contention_exhausted")

    def reserve(self, kind: BudgetDimension, *, tool_id: str = "") -> str:
        if kind == BudgetDimension.TOOL_INVOCATIONS:
            self.assert_tool_allowed(tool_id)
        else:
            self._get_validated()
        reservation_id = f"dispatch-{uuid.uuid4().hex}"
        self._cas_mutate(
            "reserve",
            member=self.member,
            reservation_id=reservation_id,
            kind=kind,
            tool_id=tool_id,
        )
        # Dispatched is persisted before the physical side effect. If this
        # mutation fails, the network/tool is NOT invoked, and the reserved
        # allocation stays conservatively charged.
        self._cas_mutate("mark_dispatched", reservation_id=reservation_id)
        return reservation_id

    def settle(self, reservation_id: str, *, outcome: str, complete: bool) -> None:
        self._cas_mutate(
            "settle",
            reservation_id=reservation_id,
            receipt_ref=f"dispatch-receipt-{reservation_id}",
            outcome=outcome,
            usage_complete=complete,
        )

    def request_stop(self, *, reason: str) -> None:
        """Latch locally before durable CAS; never claim physical closure.

        Even if persistence is uncertain, late callbacks holding this same
        execution instance cannot obtain another provider/tool permission.
        The root remains UNKNOWN across restart until reconciled.
        """
        self._local_stop.set()
        self._cas_mutate("request_stop", reason=reason)

    def seal_at_run_end(self, *, reason: str = "run_ended") -> None:
        """Seal a zero-derivation task after its owning Run has terminated.

        Cleanup must never leave a fresh/ACTIVE budget usable by a stale
        worker ContextVar. Existing STOP_REQUESTED keeps its earlier reason.
        Persist uncertainty is not physical closure; the local latch remains
        revoked even when the durable write fails.

        Future positive-wake profiles need a *member* terminal contract
        that preserves separately authorized children; I4 currently denies
        all wake/subagent derivation.
        """
        self._local_stop.set()
        snapshot = self.store.read(self.budget_id)
        if snapshot["phase"] in {BudgetPhase.ISSUED, BudgetPhase.ACTIVE}:
            self._cas_mutate("request_stop", reason=reason)


_ACTIVE_RUN_BUDGETS: dict[tuple[str, str], TaskBudgetExecution] = {}
_ACTIVE_RUN_BUDGETS_GUARD = threading.Lock()


def register_active_task_budget(execution: TaskBudgetExecution) -> None:
    """Register a *currently admitted* exact Run for cancel handoff only.

    No runtime issuer is created here; the calling Run already owns the
    Session lease and has a separately authorized budget. Registry entries
    only allow reduction/revocation, never mint additional authority.
    """
    execution._get_validated()
    key = (execution.member.session_id, execution.member.run_generation)
    if not key[0] or not key[1]:
        raise TaskBudgetDeniedError("missing_run_owner")
    with _ACTIVE_RUN_BUDGETS_GUARD:
        existing = _ACTIVE_RUN_BUDGETS.get(key)
        if existing is not None and existing is not execution:
            raise TaskBudgetDeniedError("active_run_budget_identity_conflict")
        _ACTIVE_RUN_BUDGETS[key] = execution


def unregister_active_task_budget(execution: TaskBudgetExecution) -> None:
    """Identity-scoped cleanup; a late Run-A cannot unregister Run-B."""
    key = (execution.member.session_id, execution.member.run_generation)
    with _ACTIVE_RUN_BUDGETS_GUARD:
        if _ACTIVE_RUN_BUDGETS.get(key) is execution:
            _ACTIVE_RUN_BUDGETS.pop(key, None)


def cancel_active_task_budget(
    session_id: str, run_generation: str, *, reason: str
) -> bool:
    """Revoke one active exact Run; no matching budget is a normal no-op.

    On disk/CAS uncertainty, the local latch is still revoked before this
    function raises. Caller must report the persistence failure separately;
    it MUST NOT silently infer CLOSED_VERIFIED from Runner.cancel(True).
    """
    if not session_id or not run_generation:
        return False
    with _ACTIVE_RUN_BUDGETS_GUARD:
        execution = _ACTIVE_RUN_BUDGETS.get((session_id, run_generation))
        if execution is None:
            return False
        execution._local_stop.set()
    execution.request_stop(reason=reason)
    return True


_BOUND_BUDGET: ContextVar[TaskBudgetExecution | None] = ContextVar(
    "lfl_task_budget_execution", default=None
)


def active_task_budget() -> TaskBudgetExecution | None:
    return _BOUND_BUDGET.get()


@contextmanager
def bind_task_budget(
    execution: TaskBudgetExecution, *, cleanup_scope: bool = False
) -> Iterator[None]:
    """Bind a verified execution without giving stopped work new authority.

    The LoopEngine must keep its cleanup/receipt scope alive **after** Stop.
    Only that already-authorized owner uses cleanup_scope; every actual
    provider/tool operation still invokes _get_validated and hard denies.
    Public/offline explicit bindings always validate on entry by default.
    """
    if not cleanup_scope:
        execution._get_validated()
    token = _BOUND_BUDGET.set(execution)
    try:
        yield
    finally:
        _BOUND_BUDGET.reset(token)


@contextmanager
def checked_provider_attempt() -> Iterator[None]:
    """Physical transport reservation before the HTTP client sends any bytes."""
    budget = active_task_budget()
    if budget is None:
        yield
        return
    rid = budget.reserve(BudgetDimension.PHYSICAL_ATTEMPTS)
    outcome = "interrupted"
    try:
        yield
        outcome = "success"
    except Exception:
        outcome = "failure"
        raise
    finally:
        # Provider usage has NOT been authoritatively reconciled by I2.
        # Even after a successful HTTP call, retain unknown liability.
        budget.settle(rid, outcome=outcome, complete=False)


@contextmanager
def checked_tool_dispatch(name: str) -> Iterator[dict[str, bool]]:
    outcome_fact = {"complete": False}
    budget = active_task_budget()
    if budget is None:
        yield outcome_fact
        return
    rid = budget.reserve(BudgetDimension.TOOL_INVOCATIONS, tool_id=name)
    outcome = "interrupted"
    try:
        yield outcome_fact
        outcome = "success"
    except Exception:
        outcome = "failure"
        raise
    finally:
        budget.settle(rid, outcome=outcome, complete=outcome_fact["complete"])
