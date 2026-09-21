"""Prompt-neutral multi-round convergence decision boundary.

The program owns only mechanical facts and the temporary provider tool surface. It never
decides that the user's task is complete. When bounded mechanical signals are present,
the next model round may either answer directly or call ``convergence_decide`` to reopen
the ordinary tool surface with a model-authored unresolved fact.

No system/user message is injected and no program-authored strategy prose is persisted.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConvergenceFacts:
    rounds: int = 0
    repeated_exact_call_count: int = 0
    consecutive_empty_searches: int = 0
    context_ratio: float | None = None
    goal_task_total: int | None = None
    goal_open_tasks: int | None = None
    outstanding_async_obligations: int = 0


@dataclass(frozen=True)
class ConvergenceVerdict:
    arm: bool
    reasons: tuple[str, ...] = ()


def evaluate_convergence_boundary(facts: ConvergenceFacts) -> ConvergenceVerdict:
    """Return a mechanical boundary verdict without interpreting task semantics."""
    if facts.outstanding_async_obligations > 0:
        return ConvergenceVerdict(False)

    reasons: list[str] = []
    if facts.repeated_exact_call_count >= 3:
        reasons.append("repeated_exact_call")
    if facts.consecutive_empty_searches >= 2:
        reasons.append("consecutive_empty_search")
    if facts.rounds >= 6 and facts.context_ratio is not None and facts.context_ratio >= 0.8:
        reasons.append("high_context_pressure")
    if (
        facts.goal_task_total is not None
        and facts.goal_task_total > 0
        and facts.goal_open_tasks == 0
    ):
        reasons.append("goal_frontier_closed")
    return ConvergenceVerdict(bool(reasons), tuple(reasons))
