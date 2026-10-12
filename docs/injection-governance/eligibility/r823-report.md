# R8.23 — Strict Context Cleanliness Census

Status: **BLOCKERS FOUND — CANARY BLOCKED**
Date: 2026-08-31
Audit base: detached clean `3c2a678`

## Why this audit exists

R8.22 made the matrix mechanically green (`DONE=33 / KEEP=1`), but that status still inherited an older rule: a program message could be considered acceptable if it was limited to the current human turn. The owner rule is now stricter:

> Context must stay clean and focused. Turn identity proves lifecycle, not prompt authority. Program state, warnings, recovery instructions, historical memories and observability do not enter provider context merely because they are current-turn or possibly useful.

The strict admission rule is therefore:

- current exact user input: eligible;
- model-requested tool result/protocol pairing: eligible while unresolved;
- provider-required protocol bytes: eligible;
- one uniquely bound minimal current execution identity may be eligible when genuinely required;
- everything else defaults to retrieval/control-plane/observability with zero program-authored prompt prose.

## Result

The all-green matrix was a false fixed point. R8.23 expands the inventory from 34 to 35 surfaces and reopens ten items:

`E07, E08, E12, E15, E16, E17, E18, E19, E32, E35`.

New matrix state:

- DONE: 24
- KEEP: 1
- PARTIAL: 10
- OPEN: 0
- behavior canary: **BLOCKED**
- R9: **NOT STARTED**

## Fresh provider-wire blockers

### E07 — automatic memory snapshot

R8.8 correctly made memory lifecycle turn-bound, and R8.22 removed decision/convention from automatic memory. However, ingress still performs automatic fact/procedure retrieval and persists the result as role=user `memory_snapshot` for the current turn without explicit user acceptance or model-requested retrieval.

Historical storage census: **389 snapshots / 417,908 chars / 44 sessions**.

Required closure: memory is on-demand by default. Current-turn identity is not enough; semantic bytes enter only through explicit input-side authorization or a model-requested retrieval/tool result.

### E12 — program recovery

The R4 one-shot recovery slot is non-durable, but it is still an executable natural-language program instruction. The err1210 fallback explicitly describes itself as a “programmatic user resend”, arms a recovery block telling the model to retry the current request once, and automatically projects it on the next build.

Required closure: perform deterministic rebuild/retry in the runtime control plane and record the recovery event; zero recovery instruction prose goes to the model.

### E15 / E16 — stagnation and empty-search reminders

Both still append synthetic system messages with `prompt_lifecycle=current_turn` and exact `turn_ref`. The central gate intentionally admits them to later model rounds in the same user run.

Real persisted examples exist: stagnation reminder **2 messages / 360 chars** and empty-search reminder **1 / 215 chars** in the current session corpus.

Required closure: real tool receipts/path-registry state are the evidence; breaker/replan decisions belong to program control and telemetry.

### E17 — overflow feedback

The first overflow still appends natural-language STATUS feedback and forces another LLM round so the model can decide how to react.

Required closure: overflow is a deterministic routing/compact/stop/user-visible failure boundary. No program-authored overflow prose enters provider input.

### E18 — round-exhaustion decision

At `max_iterations`, runtime still appends `[轮次决策请求]` and explicitly `continue`s into one extra model decision round.

Required closure: round budget is a hard control-plane boundary. Stop/pause or wait for explicit user continuation/strategy input instead of spending a model round on a program instruction.

## Resurrection / compatibility blockers

### E08 — legacy TIP replay

R8.15 removed the fresh generic experience producer, but `SlotKind.TIP` remains in err1210 defer reconstruction, `_tip_tail_messages` remains build-consumable, and `tip` remains in the central dynamic producer allowlist. A fresh clean process has no normal TIP producer, but hot-reload/defer compatibility can still regain prompt authority.

Required closure: remove generic TIP from the prompt allowlist and replay path. Explicit experience search remains available.

### E35 — legacy compact anchor decision frame

This surface was not represented by the previous 34-row matrix. When `COG_RUNTIME_ANCHOR_MODE=anchor`, compression may create `compact_active_state_appendix` containing `[当前决策] goal/objective` + `[下一步]`. Default/shell mode is unset/auto, so this is latent rather than fresh-default reachability, but it creates a second program-owned active-state semantic channel alongside `task_active`/Cognitive state.

Required closure: compression occurrence never creates an independent decision prompt. If current execution identity is needed, use one canonical active-state projection independent of compact mode.

## Conversational-storage blocker

### E19 — push-style runtime notices

`skip_injected_system=true` keeps these messages out of normal provider history, so this is not a primary wire leak. However, runtime still appends architecture/eval/budget/round notices into `sess.messages`.

Current storage census: **2,993 injected_system messages / 530,464 chars / 146 sessions**. Only 58 are currently typed `architecture_report`; most are legacy/untyped.

This violates the stronger separation (`program state is observable, not conversational`) and leaves session/lifecycle bookkeeping polluted even when provider-filtered.

Required closure: event/status/UI only; do not append these notices into conversational session storage.

## Lifecycle ordering blocker

### E32 — repaired resolved history can bypass retirement once

R8.19 correctly removed the model-facing interruption tip, but its ordering is wrong for eligibility:

1. resolved episode / consumed tool-span backfill runs;
2. current user is appended;
3. event/session interruption repair inserts replay-only historical messages;
4. provider build runs without rerunning lifecycle retirement.

A mechanical reproduction constructed a replay-only completed historical Q/A. Before repair, backfill found nothing; after repair both historical messages had no `resolved_episode_ref`, and `provider_view_without_resolved_episodes` returned them. Result: `provider_contains_missing_resolved=True`.

Required closure: repair before lifecycle indexing, or rerun lifecycle indexing immediately after repair and before any memory/prompt build.

## Surfaces that remain intentionally eligible

- E01 exact current user truth;
- E02 unresolved assistant(tool_calls) + tool receipt protocol pairing;
- E05 provider-required historical reasoning only at the provider-specific minimum;
- E23 one uniquely bound `task_active` identity (`goal_id + task_id + in_progress + short title`), with zero output for ambiguous/no-current-task state;
- E31 the bounded protocol/tool-schema surface under the existing tool-eligibility policy.

Everything else remains zero-prompt, retrieval-only, observability-only, or conditional on explicit user authorization.

## Non-blocking observations

- E27 fallback notices are no longer appended to future prompt history; all-failed detail is surfaced only in the current program result.
- E13/E14/E20/E21/E25/E26/E28/E29/E30/E33/E34 remain zero-prompt under their current gates.
- E19 provider filtering is working; its remaining problem is conversational storage pollution, not ordinary wire projection.
- The stale core-loop `declaration_discrepancy_correction` assertion remains independently pre-existing test debt and is not evidence against current E14 behavior.

## Gate decision

Behavior canary and R9 remain blocked. The next implementation batch should first eliminate fresh wire blockers (`E07/E12/E15/E16/E17/E18`), then close lifecycle/resurrection/storage hardening (`E32/E08/E19/E35`), with focused + adjacent + R0 + detached clean fixed-point after each bounded batch.
