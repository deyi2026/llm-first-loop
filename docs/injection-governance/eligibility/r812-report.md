# R8.12 Interop Notify / Backlog Prompt Exit

Status: **PASS / detached-clean fixed-point verified**

Implementation commit: `a25670c fix(injection): move interop notify out of prompt`

## Scope

R8.12 closes E25 `interop_notify_and_backlog`, the last matrix surface still marked OPEN after R8.11.

The previous inbox scanner mixed two different concepts:

- **notification / queue state** — job completion, scheduler non-wakeup reminders, subagent notification copies, pending backlog count;
- **external task input** — `coordinate` / `task` messages that may actually change work the model should perform.

Only the second category can plausibly deserve model input, and it remains under E26. E25 now follows the stronger rule:

> **notification state is observable/retrievable, not self-injecting.**

## Notify behavior

For `topic=notify`, both first-seen and duplicate files now:

1. remain out of `Message` construction and provider input;
2. are moved from `pending/` directly to `done/`;
3. preserve the original JSON body, ref, source and id for Web interop UI / retrieval;
4. change only `status` to `done`;
5. emit compact action telemetry (`interop.notify`, `prompt_chars=0`).

Archive failure is fail-open: the pending file is retained for a later retry and no model message is fabricated.

This is preferable to the old `processed/` path for notifications because the Web endpoint already exposes `recent_done`, so user-visible state is preserved without using the LLM as a notification transport.

## Backlog behavior

When pending files exceed the per-scan limit, build no longer creates a synthetic message such as “另有 N 条待处理消息”. Queue depth is runtime state. R8.12 records `interop.pending_backlog / observed_only` with the count, scan limit and `prompt_chars=0`; the existing `InboxWatcher` backlog diagnostics remain unchanged.

The oldest unconsumed coordinate/task file remains pending for a later scan as before.

## Subagent-report semantic check

The audit found `subagent_report` uses `topic=notify`, but it is not the only or authoritative semantic delivery path:

- `SubAgentRunner` collects every report in `SubAgentResult.reports`;
- `SpawnSubAgentTool` includes those reports in the tool receipt returned directly to the parent model.

Therefore the inbox notify copy was a duplicate second model-input channel. R8.12 archives that copy for UI/audit but no longer injects it into the parent prompt. Tests prove the parent still receives the report through the tool-result protocol while both notification bodies remain available in `done/`.

## Coordinate/task boundary

`coordinate` and `task` messages are intentionally unchanged in this batch. They are the E26 `CONDITIONAL_EXTERNAL` surface and need a separate active-task dependency test before their prompt eligibility can be tightened.

Scheduler `wake=True` already uses `topic=coordinate`, so its explicit wake semantics remain in E26. `wake=False` reminders stay `topic=notify`: they are retained as event/UI state rather than being converted into model instructions. If a channel later needs proactive user delivery (for example a direct Feishu reminder), that should be an **output-side notification path**, not a reason to restore prompt injection.

## Evidence from current artifacts

Read-only current-channel census at audit time:

- direct pending: **0**;
- done: **50 notify** (`lfl-scheduler=13`, `job-registry=37`);
- historical `pending/processed`: **168** (`notify=166`, `coordinate=2`; sources `lfl-scheduler=78`, `job-registry=90`).

Captured audit/event artifacts contain **252 occurrences** of the historical `[外部协调·from DSH]` prompt frame. This is an artifact-occurrence count, not a unique-request rate, but it confirms the interop frame reached real provider/history evidence.

## Verification

Detached clean checkout of `a25670c` passed:

- focused interop + subagent suite: **23/23 PASS**;
- broader tracked interop/watch/Web/job/subagent/background/dsh/budget/fingerprint/1210/tail suite: **PASS**;
- tracked scheduler compatibility: **16/16 PASS**;
- touched production pyright: **0 errors / 0 warnings**;
- changed tests ruff: **PASS**;
- production `interop.py` has the same two unused-import ruff findings as parent HEAD (no new lint debt);
- canonical R0 replay: **R0-1 through R0-4 PASS**;
- tracked frozen R0 directory unchanged; frozen hash remains `b54d47a31109a03d9f926f65b7a3d9f6caf3f24c0d42b1bff26fe338ee74b02a`;
- detached checkout: **clean before and after verification**.

The main worktree's untracked `tests/unit/test_schedule_wake.py` was also green pre-commit but is not claimed as part of the detached commit. Unrelated `tests/integration/test_cognitive_integration.py` worktree edits remain untouched.

## Matrix state

After E25 closure:

- `DONE=23`
- `KEEP=1`
- `PARTIAL=10`
- `OPEN=0`

Behavior canary remains **READY but not started**. Zero OPEN entries does not imply the audit is finished: the ten PARTIAL surfaces still need to be re-evaluated under the stronger program-not-self-injecting rule, beginning with E26 and other active/conditional state surfaces.
