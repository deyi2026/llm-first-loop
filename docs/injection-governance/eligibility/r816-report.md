# R8.16 — Task Execution Identity Closure

Date: 2026-08-31

Status: **PASS**

## 1. Scope

R8.16 closes E23 `task_frontier`.

The previous rule was effectively:

> active Goal + any task ledger => render the full frontier into every build.

That confused durable task availability with automatic prompt authority. The corrected rule is:

> **Only a uniquely bound current execution identity is automatic active state. The task graph is a tool.**

## 2. Current and historical evidence

### 2.1 Current ledger state

Read-only census of `data/audit/tasks/*.jsonl` found:

- task ledgers: **2**;
- tasks: **11**;
- open tasks: **0**;
- completed tasks: **11**;
- ready / in_progress / blocked / unreachable: **0 / 0 / 0 / 0**.

One Goal remains active while its two tasks are both completed. The old build condition checked `count_for_goal() > 0`, so it would still render roughly **120 chars per build** containing `open=0`, done count and task-operation guidance. No executable node exists in that state.

### 2.2 Historical execution shape

Replaying both real append-only task ledgers showed `max_concurrent_in_progress=1` for each graph. There is no current production evidence that automatic prompt state needs to represent multiple executing nodes.

### 2.3 Provider reachability

Structured parsing of frozen provider-wire fixtures found three genuine role=user dynamic messages containing `slot:task_frontier`; representative captured frames are about **322 chars**. The old producer therefore reached provider input in real executions.

## 3. Root cause

`build.py` previously called `TaskStore.render_frontier()` whenever:

1. a Goal was active;
2. its task ledger was non-empty.

`render_frontier()` is deliberately a rich inspection view. It may include:

- open/total/ready/done counts;
- ready task titles;
- in-progress task titles;
- blocked task titles and reasons;
- unreachable task ids;
- premise-stale completed tasks;
- task bookkeeping guidance.

Those fields are useful when the model explicitly inspects the graph, but ledger existence does not prove they are required for the current model decision. Completed/blocked/unreachable state can therefore become repetitive program-authored context even when the human has moved elsewhere.

The separate `task_frontier()` tool already exposes the same graph and `full=true` adds waiting/done detail. `get_goal` also retains a compact task-count summary, and `get_tool_schema` provides universal schema discovery.

## 4. Implemented boundary

Implementation commit: `06dfd6b` (`fix(injection): narrow task frontier prompt authority`).

### 4.1 Full frontier slot is centrally retired

`task_frontier` is removed from `PROMPT_DYNAMIC_PRODUCER_SLOTS`.

This is a hard future-proofing gate: a later producer cannot regain automatic prompt authority simply by appending a full graph under the old slot name.

### 4.2 New narrow `task_active` slot

`task_active` is the only automatic task-state producer. It is emitted only when:

- the Goal is active;
- a task ledger exists;
- the computed frontier contains **exactly one** `in_progress` task.

Its byte-stable payload is limited to:

```text
[Task Active] goal=<goal_id>; task=<task_id>; status=in_progress; title=<one-line title>
```

Title whitespace is normalized and capped at 80 characters. No ready/blocked/unreachable/completed counts or task-operation instructions are included.

### 4.3 Zero and ambiguity deny

Automatic task prompt chars are zero when:

- no task is in progress;
- all tasks are done;
- the graph is ready-only;
- the graph is blocked/unreachable-only;
- more than one task is in progress.

Multiple active nodes are treated as ambiguous. The program does not guess which node the model should continue.

### 4.4 Budget semantics follow the narrow surface

The injection hard-budget critical-status set now names `task_active` instead of retired `task_frontier`, preserving the intended survival priority for the one execution identity that remains eligible.

## 5. Prompt reduction

A representative graph containing one completed task, one blocked task with reason, one ready task and one current in-progress task produced:

- old full `render_frontier()`: **286 chars**;
- new `task_active`: **117 chars**;
- reduction: **169 chars / 59.1%**.

The current real all-done active Goal drops from roughly **120 chars per build to 0**.

A secondary integration signal appeared in the injection-budget suite: after the full automatic frontier disappeared, the existing production-shape fixture used **643 chars**, below its former 900-char over-budget trigger. The test now uses the supported 512-char minimum so it continues exercising over-budget receipt behavior without depending on accidental prompt bulk.

## 6. Preserved capabilities

R8.16 does not change task storage or task graph semantics:

- `TaskStore` append-only ledger remains the source of truth;
- `task_frontier()` still exposes the normal graph;
- `task_frontier(full=true)` still exposes waiting/done details;
- `get_goal` still includes a compact task summary;
- `task_create` / `task_update` lifecycle and evidence gates are unchanged;
- task tool schemas remain discoverable through normal tool eligibility / `get_tool_schema`.

The unrelated current worktree edits in `task_store.py` were not touched or staged by R8.16.

## 7. Verification

Pre-commit:

- focused task/goal/eligibility suite: **56/56 PASS**;
- broader adjacent 14-file suite: **263/263 PASS**;
- touched production + test pyright: **0 errors / 0 warnings / 0 informations**;
- `py_compile`: PASS;
- canonical R0-1 through R0-4: **PASS**;
- frozen R0 directory hash: `b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a`.

Detached-clean fixed-point at `06dfd6b` repeated:

- clean before verification;
- pyright 0/0;
- focused 56/56 PASS;
- broader 263/263 PASS;
- R0 four gates PASS;
- frozen hash byte-identical;
- clean after verification.

## 8. Matrix result

E23 moves `PARTIAL -> DONE`.

Matrix after R8.16:

- `DONE=27`
- `KEEP=1`
- `PARTIAL=6`
- `OPEN=0`

Behavior canary / R9 remain **not started**. Remaining PARTIAL surfaces are E04, E05, E06, E09, E10 and E32.
