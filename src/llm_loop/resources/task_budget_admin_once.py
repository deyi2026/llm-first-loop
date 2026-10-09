"""Administrator-configured, ONE Web session / ONE Run GLM budget.

The administrator installs one read-only-at-run-time configuration with a
random approval ID. No per-message signature, private key, Web endpoint, or
model-supplied permission exists. The first durable human event atomically
consumes that ID with the existing flock/fsync TaskBudgetStore CAS; every
subsequent event/Run/restart is denied even when the first Run sent nothing.

The guarantee is at most one attempted physical POST, NOT known GLM billing,
completed transport quiescence, or an exact token/monetary ceiling.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from llm_loop.core.trace_leak.ingress_token import IngressToken, is_whitelisted
from llm_loop.event_log.model import Event
from llm_loop.event_log.store import EventStore
from llm_loop.resources.task_budget_contracts import (
    BudgetPhase,
    TaskBudgetGrant,
    TaskBudgetMember,
)
from llm_loop.resources.task_budget_dispatch import TaskBudgetExecution, exact_workspace_scope
from llm_loop.resources.task_budget_event_authority import _event_fields, _rehydrate_event
from llm_loop.resources.task_budget_positive_authority import (
    POLICY,
    PROFILE,
    capabilities,
    limits,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError, TaskBudgetStore
from llm_loop.resources.task_budget_transport_context import (
    bind_authorized_provider_proxy,
    qualify_loopback_provider_proxy,
)

_ID = re.compile(r"[0-9a-f]{32}\Z")
_MAX_CONFIG_WINDOW_SECONDS = 3600
_RUN_DEADLINE_SECONDS = 30


@dataclass(frozen=True)
class AdminOnceEventPlan:
    session_id: str
    workspace_scope: str
    authorization_id: str
    valid_from_epoch_s: float
    valid_until_epoch_s: float
    event_store: EventStore
    budget_store: TaskBudgetStore
    provider_proxy: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.authorization_id, str) or not _ID.fullmatch(self.authorization_id):
            raise TaskBudgetDeniedError("admin_once_id_invalid")
        if (
            not isinstance(self.session_id, str) or not self.session_id
            or not isinstance(self.workspace_scope, str) or not self.workspace_scope
            or isinstance(self.valid_from_epoch_s, bool)
            or isinstance(self.valid_until_epoch_s, bool)
            or not isinstance(self.valid_from_epoch_s, (int, float))
            or not isinstance(self.valid_until_epoch_s, (int, float))
            or not 0 < self.valid_until_epoch_s - self.valid_from_epoch_s <= _MAX_CONFIG_WINDOW_SECONDS
            or not isinstance(self.event_store, EventStore) or not self.event_store.enabled
            or not isinstance(self.budget_store, TaskBudgetStore)
        ):
            raise TaskBudgetDeniedError("admin_once_plan_invalid")
        if (
            self.provider_proxy is not None
            and qualify_loopback_provider_proxy(self.provider_proxy) is None
        ):
            # Only an explicit plain-http loopback proxy may ever be pinned
            # for the one physical attempt; no env/system discovery exists.
            raise TaskBudgetDeniedError("admin_once_proxy_invalid")

    @property
    def budget_id(self) -> str:
        # The authorization ID, rather than event ID, is the durable CAS key.
        # A second human event can never mint a second physical attempt.
        return "webadminonce-" + self.authorization_id


_ADMIN_PLAN: ContextVar[AdminOnceEventPlan | None] = ContextVar(
    "lfl_web_admin_one_run_plan", default=None
)


def active_admin_once_plan() -> AdminOnceEventPlan | None:
    return _ADMIN_PLAN.get()


@contextmanager
def bind_admin_once_plan(plan: AdminOnceEventPlan) -> Iterator[None]:
    if not isinstance(plan, AdminOnceEventPlan):
        raise TypeError("admin_once_plan_required")
    with bind_authorized_provider_proxy(plan.provider_proxy):
        token = _ADMIN_PLAN.set(plan)
        try:
            yield
        finally:
            _ADMIN_PLAN.reset(token)


def prepare_admin_once_event_budget(
    *, plan: AdminOnceEventPlan, event: Event, session_id: str,
    workspace_root: str, run_generation: str, user_text: str,
    ingress: object | None,
) -> TaskBudgetExecution:
    """Consume admin approval after the human EventStore fsync, before dispatch."""
    if (
        not isinstance(ingress, IngressToken) or not is_whitelisted(ingress)
        or ingress.channel != "web" or ingress.entry != "web" or ingress.delegated
        or not run_generation or not isinstance(event, Event)
        or session_id != plan.session_id
        or exact_workspace_scope(workspace_root) != plan.workspace_scope
    ):
        raise TaskBudgetDeniedError("admin_once_human_ingress_mismatch")
    persisted = _rehydrate_event(plan.event_store, session_id, event.event_id)
    # _event_fields rejects tool/synthetic user messages and invalid provenance.
    _event_fields(persisted)
    if persisted != event or persisted.payload["content"] != user_text:
        raise TaskBudgetDeniedError("admin_once_event_mismatch")
    now = time.time()
    if not plan.valid_from_epoch_s <= now < plan.valid_until_epoch_s:
        raise TaskBudgetDeniedError("admin_once_authorization_expired")

    grant = TaskBudgetGrant(
        budget_id=plan.budget_id,
        issuer="web-admin",
        authority_source="admin-once-config-cas-v1",
        workspace_scope=plan.workspace_scope,
        session_id=session_id,
        human_turn_ref=f"event-{persisted.event_id}",
        surface="web",
        profile=PROFILE,
        policy_version=POLICY,
        deadline_epoch_s=min(now + _RUN_DEADLINE_SECONDS, plan.valid_until_epoch_s),
        limits=limits(),
        capabilities=capabilities(),
        provider_identity="glm",
        exact_model_ref="glm-5.3",
    )
    row = plan.budget_store.issue_root(
        grant, root_run_generation=run_generation,
        ingress_kind="web", reject_duplicate=True,
    )
    if row["phase"] == BudgetPhase.ISSUED:
        row = plan.budget_store.activate(
            plan.budget_id, expected_revision=row["revision"]
        )
    if row["phase"] != BudgetPhase.ACTIVE:
        raise TaskBudgetDeniedError("admin_once_budget_not_active")
    member = TaskBudgetMember.from_dict(row["members"][plan.budget_id])
    return TaskBudgetExecution(
        store=plan.budget_store, budget_id=plan.budget_id, member=member,
    )
