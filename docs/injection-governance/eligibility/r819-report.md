# R8.19 — Interruption Recovery Out-of-Band Closure

Status: **PASS**
Date: 2026-08-31
Surface: E32 `interruption_recovery_note`

## Decision

A session/event-log divergence is a deterministic runtime consistency problem, not a model task. The runtime must repair recoverable gaps itself and keep repair/failure state out of provider working context. No `[会话中断恢复]` program-authored tip is emitted.

## Root cause

The old `_inject_interruption_recovery` compared the number of `message.appended` events with `len(sess.messages)`. When the event stream was ahead it created a one-shot system tip telling the model to read event logs and continue. This had two defects:

1. It delegated deterministic state reconciliation to the LLM and polluted the current task context.
2. Count-only detection was incomplete. If an earlier run left one durable event missing from session JSON and the current ingress event append also failed, event and memory counts could be equal even though the historical message identities differed.

`SessionStore` already has deterministic event-log replay through `_load_from_event_log()` / `replay_session()`, so the model-facing recovery note was unnecessary.

## Runtime behavior

Implementation `e2f9fdd` changes E32 to program-side reconcile:

- preserve the live current-user `Message` object;
- replay the durable event stream;
- compare the replayed historical prefix with the live historical prefix using protocol/semantic message fields rather than transient timing/token fields;
- insert only replay-only historical messages immediately before the live current user;
- if replay already contains the current ingress, remove the replay copy and preserve the live object;
- refuse to guess when the historical prefix or current-user ordering is ambiguous;
- if replay is behind the live prefix, keep the live session unchanged;
- successful repair and fail-open outcomes are recorded through `run.interruption_recovery` action telemetry with `prompt_chars=0`;
- no `_tip_tail_messages`, no `_interruption_notified` prompt lifecycle, and no synthetic recovery prose.

The existing replay rule for interrupted duplicate message indices remains authoritative: event sequence order preserves both messages rather than overwriting the earlier one.

## Verification

Implementation commit: `e2f9fdd` (`fix(injection): repair interruption gaps out of band`).

Focused and real-storage coverage:
- interruption recovery + EventStore/replay/stream: **45/45 PASS**;
- includes a real `EventStore + SessionStore` duplicate-index crash/restart scenario;
- includes the equal-count replacement-gap case that the old counter could miss;
- covers replay failure, prefix mismatch, ambiguous current-user placement, event-log-behind, and aligned no-gap behavior.

Broader adjacent verification:
- core loop (excluding the independently pre-existing stale declaration-reminder assertion), SessionStore, err1210 recovery/blind/session isolation, prompt eligibility, injection fingerprint, and reference integration: **160/160 PASS**;
- the excluded declaration assertion fails identically on detached parent `5be8425` and has no EventStore in its fixture, so it is not attributable to E32;
- production/new-test pyright: **0 errors / 0 warnings**;
- py_compile: PASS;
- canonical R0-1 through R0-4: **PASS**;
- tracked frozen R0 baseline remains unchanged (`b54d47a31109a03d9f6caf3f24c0d42b1bff26fe338ee74b02a`);
- detached checkout clean before and after standard read-only mounts.

The current execution environment did not expose `ruff`, `uv`, or `uvx`, and `.venv` does not contain ruff; no dependency was installed merely to satisfy this batch. This is an unavailable lint executable, not a lint failure.

## Matrix result

E32 `PARTIAL → DONE`. Matrix becomes **DONE=30 / KEEP=1 / PARTIAL=3 / OPEN=0**. Remaining PARTIAL surfaces are E04, E05, and E06. Behavior canary / R9 remain not started.
