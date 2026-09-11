# docs/ai_rules.lite.md — Agent/maintenance playbook (version=15; development/repair safety + current-task authority + agency-first; v15 adds merge-absorb disposition, 2026-09-09)

> **Role (R8.24-A A-D2)**: reclassified from "universal model execution rules" to an
> **Agent/maintenance playbook** — read on demand by maintenance runs and operators;
> ordinary user runs reference it zero times and inject it into no prompt
> (standing assertion: tests/unit/test_model_contract_slimming.py).
> Full SoT: docs/ai_rules.md (superset; R8.24-A migration pointers in its trailing section).
> v7→v8 per-item disposition: .codeartsdoer/specs/r824_ab/lite-v7-v8-diff.md.

## Key constraints (v14 retained set)
1Honesty: verify against this round's tool receipts; never fabricate completion.
2Parameter autonomy: check params before tool calls; correct and retry after guidance.
3Stagnation: adjust or answer when repeating/no progress; do not re-verify a successful receipt. For unfamiliar commands/interfaces check current schema/code/docs first; retrieve history only for reusing a verified path, an unfamiliar failure, or insufficient current evidence. When waiting on an external event, emit one status line and stop.
6Evolution: use submit_evolution/self_evaluate when current evidence warrants it; accepted authorizes the goal, not every proposed implementation. Hard safety/authorization/protocol/data-integrity/resource/side-effect boundaries remain, but must not expand into task strategy or completion judgment. Machine Schema is the parameter truth. Human approval stays in the owning workspace/control plane; concrete UI paths/buttons/fallback channels follow current operator UI/docs and are not hard-coded here.
7Tool-first: if info exists only in tool results, fetch it first; never fabricate from priors.
12Identity: model identity follows model_catalog/architecture_status receipts, never priors.
23Current task/authority: the latest genuine user instruction is the task-authority truth. Short replies such as “continue/ok/yes/do that” bind only to the nearest relevant interaction; they do not reactivate older tasks. If that interaction explicitly requires a choice, missing parameter, or permission increase, a generic short reply must not fill the branch/parameter or widen authority; confirmation is valid only when the nearest pending action has one unambiguous meaning. Historical assistant proposals/plans and older task state/records are context only unless the current user explicitly authorizes them.
24Development/repair anti-regression: before changing behavior, verify the exact source and stable recovery ref, the model-visible input, qualification on the current runtime, program/model responsibility boundaries, and final gates against the staged/isolated candidate. Every real incident needs a regression test. See RULE-AI-24 and docs/DEVELOPMENT_REPAIR_SAFETY.md.

**Merge absorb disposition** (2026-09-09): before merging a parallel line (e.g. lfl/main) into the integration line, if `git rev-list HEAD..<branch>` is non-empty, record a per-commit disposition for every second-parent commit (absorbed into which commit / rejected + why); never skip silently via `-s ours`; after merging, re-verify that rev-list is empty.

## Disaster safety (hard constraint, do not touch)
Destructive commands are hard-blocked; production deploys/artifact releases/force-pushes/environment teardown need human approval.
