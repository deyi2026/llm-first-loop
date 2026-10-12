# A3 Action-Plane Guard — Development Note v1

> Status: DEVELOPMENT ONLY. A2 confirmation data is not A3 performance data.

A2 localized the main Full-Slim failure to action-loop instability, especially A2-043 / DeepSeek / G01: final semantics were correct, but the model continued tool calls after sufficient evidence and after the source limit.

A3-D introduces an experimental Action-Plane mechanism without modifying frozen `scripts/calib/runner.py`:

- `C0-NoGuard`: legacy action behavior.
- `C1-DuplicateSuppression`: identical deterministic tool+canonical-args calls reuse the prior result instead of executing again.
- `C2-BudgetTerminal`: after two actual source executions, `request_fixture` is removed from later rounds and `tool_budget_exhausted` is exposed in the final allowed tool result.
- `C3-CombinedGuard`: duplicate suppression + budget-terminal.

All four use the exact same Full-Slim-v1 system prompt. The guard has no access to expected sources, oracle decisions, or decision relevance.

Development regression only: replaying A2-043's six observed source attempts through C3 records all six attempted actions, executes only the first two, and blocks the remaining four after terminal budget. A looping fake LLM under C2 reaches final after the tool is removed; the identical fake under C0 reaches ROUND_LIMIT. These tests calibrate mechanism behavior only and cannot validate A3 effectiveness.
