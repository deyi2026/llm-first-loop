# I4-C: exact Run Stop bridge and terminal budget sealing (2026-10-09)

**Candidate only.** Parent main `5ebce6c63`; no change to live service,
config, issuer, model billing scope, wake or subagent capabilities.

## What is connected

- When the offline-only task-budget intent is accepted after the real
  Session run lease, `run_stream` registers the exact
  `(session_id, run_generation)` and existing TaskBudgetExecution in a
  process-local **revocation-only** table. The table has no issuer or
  capability to increase any existing quota.
- `BackgroundRunner.cancel` invokes the new exact-generation budget
  stop alongside the existing session-owned tool cancellation. An
  unrelated session or later Run generation cannot be revoked through
  the old identity.
- Because Stop may be accepted before budget registration, run
  admission rechecks `runner.is_cancelled(session_id)` immediately after
  registration, under the same admitted Run identity. A pre-registration
  accepted Stop is written into the root before any model call.
- TaskBudgetExecution first sets a thread-safe **local stop latch**
  and only then attempts durable root CAS. A failed disk write cannot
  release another provider/tool admission in a callback holding that
  execution object. Disk failure still remains an operational
  **PERSISTENCE_UNCERTAIN** condition; no physical closure is inferred.
- `run_stream` retains a non-granting *cleanup scope* even after Stop,
  allowing its own history/tool-receipt and contextvar cleanup instead
  of failing while trying to enter a revoked context. Every actual
  physical provider/tool dispatch still checks the authoritative
  budget and fails closed.
- Terminal Run cleanup **seals** any remaining ACTIVE root with
  `run_ended` before releasing the Session lease, then removes exactly
  that registration. A late callback cannot consume a completed Run's
  grant. Previously persisted `user_stop` is not overwritten.

## Verified negative control paths

The real LoopEngine/BackgroundRunner test with a fake provider checks
that Stop accepted in the Run-published / budget-not-yet-registered
window persists a STOP_REQUESTED root and calls **zero** FakeLLM
providers. Other tests independently cover:

- mismatch session/generation no-op (no budget changes);
- exact Run cancellation latches the matching root only;
- root CAS persistence fault retains in-process denial;
- cleanup binding can continue but grants no new action;
- terminal Run stores STOP_REQUESTED and removes the registration;
- stale context holding the completed budget cannot regain admission;
- ordinary **unbound** Run and existing Runner.cancel APIs retain
  their legacy behavior.

## Explicitly not proven

1. This maps only *already accepted offline test* budgets; production
   Web/SSE, Feishu and Learning do not mint one. The table is local,
   not a cross-process signer.
2. A locally latched Stop does not revoke unknown remote workers in
   another process after restart if the durable stop write failed.
3. Neither an in-flight blocked socket nor remote provider billing is
   proven to stop at Stop ACK; ROOT CLOSED_VERIFIED remains prohibited.
4. This zero-derivation phase seals the root at Run end. Positive
   future wake/subagent profiles need separately qualified child/member
   terminal authority and cannot reuse this single-Run seal blindly.
5. Exact model token/cost limits and live GLM-5.3 product identity
   remain UNKNOWN/HOLD. No real-model experiment is authorized.

**Production ruling:** after full R9, default-OFF compatibility rollout
can be proposed with an explicit managed release approval. Live budget
enforcement and Web Canary are **not** qualified by these tests.
