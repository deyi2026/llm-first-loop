# R8.13 — Conditional External Input Authority Closure

Date: 2026-08-31

Status: **PASS**

## 1. Scope

R8.13 closes E26 `interop_coordinate_or_task`. The problem is not whether an external message is useful; it is **who is allowed to grant it task/prompt authority**.

Owner rule:

> External state is retrievable, not automatically injectable. `target_session`, `ref`, recency, or watcher arrival are routing/observability facts, not user authorization.

## 2. Root cause found

Before R8.13, pending `coordinate` / `task` files were consumed by `_interop_inbox_messages()` and converted into program-authored prompt material. With `INBOX_WAKEUP=1`, `factory._inbox_wakeup()` then selected the most-recent session (or `default`) and started a background run with a synthetic user text: `协调通道有新消息待处理，请查收并处理（见本轮注入）`.

That created two independent authority errors:

1. **cross-session guessing** — the runtime inferred the target conversation from recency even when the external protocol did not bind the message to that session;
2. **program-as-user escalation** — the runtime fabricated a user turn to make the model process external state.

A read-only census of the current interop store found only two historical `coordinate` records, both scheduler wake messages whose `ref` is `sched-*`; neither carries a target session identity. This is concrete evidence that “use the recent session” was not a valid relation proof.

## 3. Implemented boundary

### 3.1 Pending coordinate/task stays pending

`src/llm_loop/core/loop/interop.py` now treats `coordinate` / `task` as external pending state:

- no `Message` is created;
- no provider prompt chars are emitted;
- the pending file is not auto-consumed into `processed/`;
- a compact action can record id/topic/source/ref with `prompt_chars=0`;
- repeated scans are de-duplicated for observability.

The body remains durable in the interop store/Web UI. The runtime does not silently discard it.

### 3.2 Watcher no longer guesses a conversation

`src/llm_loop/factory.py` no longer writes the notification event to the “most recent” session. `_on_inbox_notify` records global action observability only.

The legacy wake callback also no longer calls `BackgroundRunner.start(...)`. Even when `INBOX_WAKEUP=1`, it records `blocked_no_user_authorization`; it does not fabricate a `user_text` and does not start the model.

### 3.3 Legacy in-memory replay is retired

A pre-upgrade `_interop_tail_messages` / err1210 deferred interop item cannot regain provider authority on a later build. `_inject_interop_messages` clears the legacy interop tail and removes interop deferred replay refs before normal tail aggregation.

Low-level err1210 parser/defer compatibility remains testable, but engine-level recovery fixtures now use still-eligible `tip`/`hotcard` material rather than pretending interop is an active prompt producer.

### 3.4 Central allowlist closed

Follow-up commit `d2fc3fe` removes `interop` from `PROMPT_DYNAMIC_PRODUCER_SLOTS` in `src/llm_loop/core/prompt_eligibility.py`.

Therefore a future producer cannot regain model visibility merely by labelling material as `slot_kind="interop"`. The central eligibility gate denies it before profile/budget projection.

## 4. Authorization rule going forward

R8.13 intentionally does **not** treat `target_session` as sufficient authorization. Targeting only says where a message belongs; it does not say the user wants it to alter the current model task.

The only permitted future upgrade path is an input-side user action such as **accept / insert into conversation**. That action must turn the selected external item into genuine user-authorized task input. Until then the item stays pending/retrievable and has zero automatic prompt authority.

No automatic accept/insert UX is introduced in this batch; absence of that convenience is safer than restoring implicit prompt injection.

## 5. Verification

Implementation commits:

- `8cd2884` — `fix(injection): require authorization for interop tasks`
- `d2fc3fe` — `fix(injection): retire interop prompt eligibility`

Final detached-clean fixed-point at `d2fc3fe`:

- production pyright: **0 errors / 0 warnings / 0 informations**;
- focused E26/eligibility/1210/golden suite: **PASS**;
- broader tracked interop + watcher + Web API + scheduler + job + subagent + factory + 1210 + eligibility + model-attribution suite: **PASS**;
- R0-1 data completeness: **PASS**;
- R0-2 baseline measurable: **PASS**;
- R0-3 deterministic reproduction: **PASS**;
- R0-4 parameter candidate gate: **PASS**;
- detached checkout: clean before and clean after.

Main-worktree-only `tests/unit/test_schedule_wake.py` (an unrelated/untracked parallel change) also passed 5/5 as supplementary compatibility evidence and was not included in either E26 implementation commit.

## 6. Matrix result

E26 moves `PARTIAL -> DONE`.

Matrix after R8.13:

- `DONE=24`
- `KEEP=1`
- `PARTIAL=9`
- `OPEN=0`

`behavior_canary_gate_state=READY` remains only a gate state. Behavior canary / R9 are **not started** by this batch.
