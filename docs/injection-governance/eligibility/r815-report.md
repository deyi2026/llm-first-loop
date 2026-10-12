# R8.15 — Experience Catalog On-Demand Closure

Date: 2026-08-31

Status: **PASS**

## 1. Scope

R8.15 closes E08 `experience_tip`. The old path ran after tool execution and automatically projected an experience/skill catalog when a tool name matched and the session was inside the first K human turns or an explicit task-switch turn.

The governing distinction is:

> **Related / unseen / early-turn is not the same as required-now.**

Experience remains a durable capability. Generic experience catalogs are now retrieved explicitly; current failure recovery remains a separate, event-triggered path.

## 2. Historical reachability

Structured session/event census found:

- canonical `metadata.injection_kind=experience_tip`: **122** persisted messages;
- affected sessions: **34**;
- event-log files: **35**;
- role: **122/122 user**;
- stored tip text: **49,854 chars** total, p50 **338**, p90 **702**, max **834**;
- formats: **116 legacy prose**, **6 R3 pointer**;
- 103 rows had `turn_ref`; median **75**, max **2091**, and **46** were above turn 100.

R3 pointer rows also appeared at turns 15, 30 and 75. This demonstrates that task-switch reopening could continue far beyond front-K and still did not prove current necessity.

The current experience directory has **132** documents, **130 active**, so the automatic candidate space is large rather than dormant.

## 3. Root cause

`_inject_experience_tips()` used:

- first-K/task-switch eligibility;
- tool-name lookup (`ExperienceStore.list_active(query=tool_name)`);
- seen-ref deduplication;
- up to four 2-line experience/skill reference frames.

These mechanisms control volume and duplication; they do not establish task authority. The resulting frames were persisted as role=user program messages, so they could remain in later flat provider history. Existing provider eligibility filters had no dedicated `experience_tip` retirement rule.

The previous matrix evidence that resolved-episode retirement covered E08 was too indirect: `episode_history.py` has no dedicated experience-tip contract. R8.15 therefore closes the producer and provider-view lifecycle explicitly.

## 4. Implemented boundary

Implementation commit: `d04986b` (`fix(injection): retire automatic experience catalogs`).

### 4.1 Generic catalog producer is prompt-neutral

`src/llm_loop/core/loop/tool_exec.py::_inject_experience_tips` remains only as a compatibility hook. When enabled and passed tool names, it may record:

`experience.catalog / on_demand_only / prompt_chars=0`

It does **not**:

- query `ExperienceStore`;
- scan/match skills;
- create `Message` objects;
- append session history/events;
- allocate a prompt slot.

`tool_experience_inject=false` keeps the compatibility hook fully silent.

### 4.2 Historical catalogs are centrally retired

`current_turn_program_prompt_eligible()` now returns false for every canonical `metadata.injection_kind=experience_tip` message.

This applies to:

- legacy prose catalogs;
- R3 pointer catalogs;
- old-turn catalogs;
- even a same-turn catalog whose `turn_ref` matches the current human turn.

Same-turn identity proves age, not required-now necessity. Ordinary human text mentioning `experience_tip` is unaffected because it does not carry program metadata.

### 4.3 Explicit retrieval remains

`ExperienceStore` and `RecordSearcher` are unchanged. `search_records(kind=experience)` still supports keyword retrieval and exact `experience:<id>` hydration.

### 4.4 Current-failure recovery remains

The tool failure path is intentionally separate and unchanged:

- typed `recovery_advice` remains preferred when present;
- failure-specific experience guidance remains available when typed recovery is absent;
- success results do not gain generic experience guidance.

This path is triggered by a real current failure, unlike the retired generic post-tool catalog.

## 5. Verification

Before commit:

- focused generic-catalog/reference/turn/provider tests + explicit experience retrieval + failure recovery: **132/132 PASS**;
- broader tool-loop/pipeline/history/1210/session-isolation/reference suite: **288/288 PASS**;
- production pyright (`tool_exec`, `prompt_eligibility`, `build`, `registry`, `search`): **0 errors / 0 warnings / 0 informations**;
- `py_compile`: PASS;
- R0-1 through R0-4: **PASS**.

Final detached-clean fixed-point at `d04986b` repeated the same gates:

- production pyright: 0/0;
- focused/preserved-capability suite: 132/132 PASS;
- broader suite: 288/288 PASS;
- R0 four gates: PASS;
- checkout clean before and after verification.

## 6. Matrix result

E08 moves `PARTIAL -> DONE`.

Matrix after R8.15:

- `DONE=26`
- `KEEP=1`
- `PARTIAL=7`
- `OPEN=0`

Behavior canary / R9 remain **not started**. The next risk-prioritized surface is E23 `task_frontier`.
