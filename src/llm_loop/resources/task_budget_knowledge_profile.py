"""Fixed opt-in allowance for a single read-only knowledge consumption Run.

This supplies factual resource/side-effect boundaries, not applicability or
benefit judgments. No issuer, executor, automatic activation or new store.
The previous one-attempt profile remains frozen. Paid use requires approval.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from llm_loop.resources.task_budget_contracts import TaskBudgetCapabilities, TaskBudgetLimits
from llm_loop.resources.task_budget_store import TaskBudgetDeniedError

PROFILE = "web-glm-knowledge-consumption-v1"
POLICY = "knowledge-consumption-admin-once-v1"
CONFIG_SCHEMA = "web-task-budget-knowledge-consumption/v1"
RUN_DEADLINE_SECONDS = 180
READ_TOOLS = frozenset({"search_records"})
USE_TOOLS = frozenset({"method_manage", "refine_experience"})


def limits() -> TaskBudgetLimits:
    # Count retries as attempts. No unqualified round/token/billing cap.
    return TaskBudgetLimits(physical_attempts=4, tool_invocations=8)


def capabilities() -> TaskBudgetCapabilities:
    return TaskBudgetCapabilities(
        allowed_tools=READ_TOOLS | USE_TOOLS, allow_wake=False, allow_subagents=False,
    )


def assert_tool_action(name: str, arguments: Mapping[str, Any] | None) -> None:
    """A tool name alone must not authorize source mutation or promotion.

    record_use is a model declaration; existing handlers still validate its
    exact ref and bounded fields. The model may skip a card or stop the Run.
    """
    kind = arguments.get("kind") if arguments is not None else None
    if name in READ_TOOLS and isinstance(kind, str) and kind in {"method", "experience", "lesson"}:
        return
    if name in USE_TOOLS and arguments is not None and arguments.get("action") == "record_use":
        return
    raise TaskBudgetDeniedError("knowledge_consumption_tool_action_not_allowed")
