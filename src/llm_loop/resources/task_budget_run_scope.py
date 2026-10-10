"""I4-A: bounded, **offline-only** signed-Run budget attachment.

No Web route, factory, service config, scheduler or other production surface
installs this intent. Only explicit in-process test code can attach a policy.
The intent permits ZERO provider physical attempts and ZERO tool invocations.
It is not a live provider grant and must not be used to claim production
budget enforcement has been activated.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from llm_loop.core.trace_leak.ingress_token import IngressToken, is_whitelisted
from llm_loop.resources.task_budget_contracts import (
    TaskBudgetCapabilities,
    TaskBudgetGrant,
    TaskBudgetLimits,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_dispatch import (
    TaskBudgetExecution,
    exact_workspace_scope,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore


@dataclass(frozen=True)
class OfflineBudgetIntent:
    store: TaskBudgetStore
    session_id: str
    workspace_scope: str
    issuer: str = "offline-operator"
    profile: str = "offline-zero-provider-zero-tool"
    deadline_epoch_s: float = 0.0


_EXPLICIT_OFFLINE_INTENT: ContextVar[OfflineBudgetIntent | None] = ContextVar(
    "lfl_explicit_offline_budget_intent", default=None
)


@contextmanager
def bind_offline_budget_intent(intent: OfflineBudgetIntent) -> Iterator[None]:
    """Test-only authority precursor; never a signer exposed to tool/model."""
    if not isinstance(intent, OfflineBudgetIntent):
        raise TypeError("offline intent requires typed fixture authority")
    token = _EXPLICIT_OFFLINE_INTENT.set(intent)
    try:
        yield
    finally:
        _EXPLICIT_OFFLINE_INTENT.reset(token)


def prepare_offline_run_budget(
    *,
    session_id: str,
    workspace_root: str,
    run_generation: str,
    ingress: object | None,
) -> TaskBudgetExecution | None:
    """Mint a single root from exact, non-delegated human ingress after Run lease.

    Calls without an explicit test-only intent are byte-for-byte no-ops.
    A forged/foreign/expired intent must fail-closed before the first provider
    request; never fall back to the unbudgeted path after selection.
    """
    intent = _EXPLICIT_OFFLINE_INTENT.get()
    if intent is None:
        return None
    if (
        not isinstance(ingress, IngressToken)
        or not is_whitelisted(ingress)
        or ingress.delegated
        or ingress.entry not in {"web", "test_harness"}
    ):
        raise TaskBudgetDeniedError("no_authorized_human_ingress")
    scope = exact_workspace_scope(workspace_root)
    if intent.session_id != session_id or intent.workspace_scope != scope:
        raise TaskBudgetDeniedError("offline_budget_scope_mismatch")
    if not run_generation:
        raise TaskBudgetDeniedError("missing_run_generation")
    deadline = intent.deadline_epoch_s
    if deadline <= time.time():
        raise TaskBudgetDeniedError("offline_budget_deadline_expired")
    budget_id = f"runbudget-{run_generation}"
    turn_ref = f"human-{run_generation}"
    grant = TaskBudgetGrant(
        budget_id=budget_id,
        issuer=intent.issuer,
        authority_source="verified-local-offline-intent",
        workspace_scope=scope,
        session_id=session_id,
        human_turn_ref=turn_ref,
        surface="offline_test",
        profile=intent.profile,
        policy_version="I4-A-offline-v1",
        deadline_epoch_s=deadline,
        limits=TaskBudgetLimits(
            logical_calls=1,
            physical_attempts=0,
            rounds=1,
            tool_invocations=0,
        ),
        capabilities=TaskBudgetCapabilities(
            allowed_tools=frozenset(),
            allow_wake=False,
            allow_subagents=False,
        ),
    )
    row = intent.store.issue_root(
        grant, root_run_generation=run_generation, ingress_kind=ingress.entry
    )
    if row["phase"] == "issued":
        row = intent.store.activate(budget_id, expected_revision=row["revision"])
    if row["phase"] != "active":
        raise TaskBudgetDeniedError("offline_budget_not_active")
    member = TaskBudgetMember.from_dict(row["members"][budget_id])
    return TaskBudgetExecution(store=intent.store, budget_id=budget_id, member=member)
