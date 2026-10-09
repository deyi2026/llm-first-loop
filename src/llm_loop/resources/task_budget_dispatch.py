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

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
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


@dataclass(frozen=True)
class TaskBudgetExecution:
    store: TaskBudgetStore
    budget_id: str
    member: TaskBudgetMember

    def _get_validated(self) -> dict[str, Any]:
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
        """Revoke *future* admissions. Never claim in-flight physical closure."""
        self._cas_mutate("request_stop", reason=reason)


_BOUND_BUDGET: ContextVar[TaskBudgetExecution | None] = ContextVar(
    "lfl_task_budget_execution", default=None
)


def active_task_budget() -> TaskBudgetExecution | None:
    return _BOUND_BUDGET.get()


@contextmanager
def bind_task_budget(execution: TaskBudgetExecution) -> Iterator[None]:
    """Explicit (currently offline-only) propagation, never a model text grant."""
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
