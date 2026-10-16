"""Opt-in, operator-pinned Web GLM-5.3 *direct-child* canary allowance.

This profile is deliberately separate from one-physical-attempt and knowledge
consumption authorities.  It does not issue approvals, set environment variables,
authorize recursive agents, or make changes to production by default.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from llm_loop.resources.task_budget_contracts import (
    TaskBudgetCapabilities,
    TaskBudgetLimits,
)
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError

PROFILE = "web-glm-direct-subagent-canary-v1"
POLICY = "web-direct-subagent-host-gate-v1"
CONFIG_SCHEMA = "web-task-budget-direct-subagent-canary/v1"
RUN_DEADLINE_SECONDS = 180
PARENT_TOOLS = frozenset({"spawn_subagent", "subagent_result"})
MODEL_REF = "glm/glm-5.3"
# Conservative accounting: all parent and one child physical attempts share
# the same durable ledger. Every attempt (including uncertain) is charged.
MAX_PHYSICAL_ATTEMPTS = 8
MAX_TOOL_INVOCATIONS = 3


def limits() -> TaskBudgetLimits:
    return TaskBudgetLimits(
        physical_attempts=MAX_PHYSICAL_ATTEMPTS,
        tool_invocations=MAX_TOOL_INVOCATIONS,
    )


def capabilities() -> TaskBudgetCapabilities:
    return TaskBudgetCapabilities(
        allowed_tools=PARENT_TOOLS,
        allow_subagents=True,
        allow_wake=False,
    )


def assert_parent_tool_action(
    name: str, arguments: Mapping[str, Any] | None,
    *, child_members: frozenset[str] = frozenset(),
) -> None:
    """Constrain delegated effects at the physical tool boundary, not prompt-only.

    Every parent spawn must create a zero-tool GLM child; only direct result
    lookup is allowed. Any shape mismatch consumes no grant and dispatches
    neither a tool nor a provider call.
    """
    if not isinstance(arguments, dict):
        raise TaskBudgetDeniedError("subagent_canary_arguments_required")
    if name == "spawn_subagent":
        keys = set(arguments)
        if keys - {"task", "context", "inherit", "model", "requires", "acceptance"}:
            raise TaskBudgetDeniedError("subagent_canary_spawn_extra_fields")
        task = arguments.get("task")
        if not isinstance(task, str) or not 1 <= len(task.strip()) <= 600:
            raise TaskBudgetDeniedError("subagent_canary_task_invalid")
        if arguments.get("inherit", False) is not False:
            raise TaskBudgetDeniedError("subagent_canary_inherit_denied")
        if arguments.get("model", "") not in ("", MODEL_REF):
            raise TaskBudgetDeniedError("subagent_canary_child_model_denied")
        if arguments.get("context", "") not in ("", None):
            raise TaskBudgetDeniedError("subagent_canary_inherited_context_denied")
        if arguments.get("acceptance", []) not in ([], None):
            raise TaskBudgetDeniedError("subagent_canary_acceptance_denied")
        if arguments.get("requires") != {"tools": []}:
            raise TaskBudgetDeniedError("subagent_canary_child_must_have_zero_tools")
        return
    if name == "subagent_result":
        if set(arguments) - {"child_id", "wait_seconds"}:
            raise TaskBudgetDeniedError("subagent_canary_result_extra_fields")
        child_id = arguments.get("child_id")
        if not isinstance(child_id, str) or child_id not in child_members:
            raise TaskBudgetDeniedError("subagent_canary_direct_child_required")
        wait = arguments.get("wait_seconds", 0)
        if isinstance(wait, bool) or not isinstance(wait, (int, float)) or not 0 <= wait <= 10:
            raise TaskBudgetDeniedError("subagent_canary_wait_out_of_range")
        return
    raise TaskBudgetDeniedError("subagent_canary_tool_not_allowed")
