# M5-F — Real Run terminal producer: minimal safety closeout

Status: isolated implementation candidate, **not automatic recovery approval**.
Parent: M5-E `7671f81a589f7a13d45ed42d7f260b5c8467f187`.

## Problem and minimal fix

M5-A/B could strictly persist `run.durable.opened` and
`run.durable.admission_fenced`, but the production finalizer emitted ordinary
fail-open `run.end` without the Run generation; the Run lifecycle sealed
TaskBudgetStore without emitting `run.durable.terminal`. Therefore the
read-only M5 recovery reducer could not join a real completed Run to its
durable admission and budget seal.

The change touches only three runtime files:

1. `run_finalizer.py`: add the actual ContextVar `run_generation` to
   the existing `run.end` payload (no new EventStore or budget source).
2. `task_budget_t1_web_profile.py`: override only the existing T1
   `seal_at_run_end` hook. The unchanged production lifecycle calls it
   under the SessionStore run lease; after the parent budget seal it invokes
   the strict terminal producer only for a durably fenced T1 execution.
3. `durable_run_recovery.py`: verify the original strict admission revision,
   sealed budget identity, one real persisted `run.end` matching the exact
   Run generation and `reason=completed`, then append
   `run.durable.terminal` via existing strict file+directory fsync/readback.
   Missing, ambiguous or uncertain evidence emits no terminal and stays HOLD.

This is a **local Run-end fact**, not an assertion that Provider transport
settled or that a Tool mutation has a causal receipt. A completed local
`run.end` with dispatched Provider/Tool reservations may have a terminal
event but the M5 read-only reducer **must still return HOLD**. A
`completed_verified` verdict is possible only for the reducer's already
specified zero-effect, no-reservation, no-unknown-event case. In every case
`auto_resume_allowed=false` and `old_run_replay_allowed=false`.

## Verification

Targeted cases cover actual engine `run.end` generation, strict completed
zero-effect event join, idempotence, mismatched generation, cancelled/error,
missing/duplicate `run.end`, active budget, strict append failure, real T1
engine adapter denial, and dispatched Provider liability remaining HOLD.
The M5-E 15 real POSIX SIGKILL and dual-worker tests remain unchanged and
continue to pass. Provider transport is **never** called in these new tests.

This is intentionally **not** a second WAL, second budget ledger, new
scheduler, or a new retry/replay pathway. No Web/SSE/queue API behavior is
changed. No production host, Deepin, main or old M4-C evidence is modified.

## Open evidence gaps — do not turn into hidden extra work

- No authenticated remote Provider settlement ID / remote billing ACK for
  the old M4-C liability; it remains `QUARANTINED_UNRESOLVED/HOLD`.
- Tool reservation-to-effect causal identity remains unproven for arbitrary
  crashes; matching final file bytes is not proof of which worker wrote them.
- This candidate has no successful **real remote Provider** T1 Run. Fake
  engine tests exercise the actual local finalizer and negative T1 entrypoint;
  a positive strict zero-effect join is exercised with real EventStore and
  TaskBudgetStore but a synthetic `run.end` producer in the unit test.
- Sudden power loss, every possible interleaving, and arbitrary production
  automatic resume are **not** proven.

## Freeze and release gates

Independent GLM-5.3 reviewer must report `completed/PASS/P0=0/P1=0`
on the exact frozen patch, followed by original unmodified
`bash scripts/ci_gate.sh` with real exit 0. If remote GitHub gates,
architecture review or privacy scan cannot be verified, retain an isolated
handoff and **do not** silently integrate/push main or restart. The unrelated
active Console Goal for local-model drift must not be overwritten by M5
checkpoints; use this worktree's local receipts until a genuinely separate
M5 Console session is available.

The M5-E acceptance document describes its own earlier snapshot and remains
historically correct. This document supersedes only its *missing terminal
producer* item, not its broader auto-resume HOLD verdict.
