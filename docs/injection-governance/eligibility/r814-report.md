# R8.14 — Task Handoff Authorization Closure

Date: 2026-08-31

Status: **PASS**

## 1. Scope

R8.14 closes E24 `task_hotcard` under the same authority rule used for E26 external input:

> Durable state is retrievable; crossing a session boundary does not grant prompt authority.

The card remains useful as a handoff/index artifact. What is removed is the runtime assumption that a new session automatically means “continue the previous task.”

## 2. Root cause and live counterexample

Before R8.14, `pop_hotcard()` considered an unconsumed card eligible whenever `origin_session != current_session`. `build.py` called it automatically on every build, immediately marked the card consumed, and appended the resulting pointer as a live `HOTCARD` prompt slot. If a 1210 recovery stripped that slot, err1210 could reset `consumed` and make the card eligible again.

This made **cross-session identity a substitute for user intent**.

The current real `data/handoff/task_hotcard.json` supplied a direct counterexample during the audit: it was still `consumed=false`, while its anchor belonged to an unrelated MLX/model task and its `active_goals` snapshot still contained a much older injection-governance R0→R1 checkpoint. A fresh unrelated session would therefore have been eligible for an internally stale/mixed handoff solely because its session id differed.

A structured event-log census found no runtime-like `[任务热卡]` frame in current `payload.content`; the three text matches were tool/source-code outputs. This is therefore a **mechanically reachable, currently armed risk** rather than a claim of already widespread live pollution.

## 3. Implemented boundary

### 3.1 Write side stays durable

`write_hotcard()` is retained. Compression can still write `data/handoff/task_hotcard.json` with anchor, active-goal/checkpoint and pending-evolution state.

No recovery information is deleted.

### 3.2 Default pop/reset has no authority

`pop_hotcard(..., authorized=False)` now returns `None` before reading or mutating the card. `reset_hotcard_consumed(..., authorized=False)` similarly returns `False` without changing durable state.

Only an input-side flow that has already established user restore/accept authority may call either helper with `authorized=True`.

`origin_session != session_id`, `consumed=false`, recency, or a matching ref are availability/routing facts, not authorization.

### 3.3 Build no longer auto-hydrates hotcard

`src/llm_loop/core/loop/build.py` no longer calls `pop_hotcard()` and no longer appends `SlotKind.HOTCARD` to `_inject_parts`.

A pre-upgrade in-memory HOTCARD deferred marker is retired with `prompt_chars=0` observability rather than replayed.

### 3.4 Err1210 cannot resurrect the card

If a legacy HOTCARD injection entry reaches `_defer_store`, err1210 records:

`defer_dropped(reason=prompt_eligibility_retired)`

and removes the slot. It does not reset `consumed`, does not add a HOTCARD replay marker and does not create another prompt opportunity.

### 3.5 Central eligibility gate closed

`hotcard` is removed from `PROMPT_DYNAMIC_PRODUCER_SLOTS` in `src/llm_loop/core/prompt_eligibility.py`.

Semantic classification may still recognize a historical hotcard as reference material; classification is not eligibility. A future producer cannot regain automatic provider access merely by choosing the old slot name.

## 4. Recovery capability remains available

The audit verified two durable explicit recovery paths:

1. the full hotcard JSON remains readable at `data/handoff/task_hotcard.json`;
2. `handoff_now` writes `handoff.md` and archives it into the current `ArchiveStore`; existing `tests/unit/test_handoff_archive.py` proves the content is retrievable via archive search.

Therefore R8.14 removes implicit continuation authority without deleting handoff evidence or requiring a new recovery subsystem.

A future UI/tool may implement **accept/restore handoff**. That input-side action can explicitly authorize a selected artifact and then turn it into genuine user-authorized task input. R8.14 deliberately does not infer that action from session transition.

## 5. Golden morphology impact

Retiring the live HOTCARD slot intentionally changed the deterministic injection morphology. The golden test red-lit as designed and was reviewed/rebased from memory+tip+hotcard to memory+tip only.

New golden digest:

`59a823f60750e5b96565bf46057f141e33d7e328ae0b67b3e3a250dfa5ac5e64`

A dedicated test now proves that writing a durable hotcard does not change provider wire and does not set `consumed`.

## 6. Verification

Implementation commit:

- `223472c` — `fix(injection): require authorization for task handoff`

Pre-commit verification:

- focused E24/handoff/eligibility/1210/golden: **89/89 PASS**;
- broader adjacent archive/history/context-budget/cache-breaker/handoff/1210/reference/user-truth/model-attribution: **289/289 PASS**;
- production pyright: **0 errors / 0 warnings / 0 informations**;
- `py_compile`: PASS;
- R0-1 through R0-4: **PASS**;
- tracked frozen fixture data unchanged.

Final detached-clean fixed-point at `223472c` repeated the same gates:

- production pyright: 0/0;
- focused: 89/89 PASS;
- broader: 289/289 PASS;
- R0 four gates: PASS;
- checkout clean before and after verification.

Before this batch, `tests/unit/test_task_hotcard.py` already had two stale R3 assertions expecting the pointer view to reproduce anchor prose. Those were baseline test debt, not E24 regressions; R8.14 replaces them with the current pointer + authorization contract.

## 7. Matrix result

E24 moves `PARTIAL -> DONE`.

Matrix after R8.14:

- `DONE=25`
- `KEEP=1`
- `PARTIAL=8`
- `OPEN=0`

Behavior canary / R9 remain **not started**. The next highest-risk remaining surface is E08 `experience_tip` because current experience pointers still lack a complete required-now eligibility gate.
