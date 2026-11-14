# M5-E: real process-kill and dual-worker negative acceptance

Status: isolated offline candidate; **NOT production arbitrary-crash auto-resume**.
Parent M5-D frozen commit: `84b0b5e910496d07ca9f2db417fe323a7365fe97`.

## Scope and actual execution

The new pytest harness uses real child Python processes, real POSIX SIGKILL
(`Popen.kill` with negative SIGKILL return code), explicit fsynced stage
markers, and the production EventStore, TaskBudgetStore, T1 Web admission
helper, SessionStore run_lease and FileService. Each case has a fresh pytest
temporary workspace and no external network transport. It never contacts
GLM, creates a new real Provider request, replays an old Run, or modifies
production services.

| Fault boundary | Physical process and evidence | Expected restart verdict |
| --- | --- | --- |
| Before `run.durable.opened` | Budget root already ACTIVE; no strict facts | HOLD; old authorization cannot issue again |
| After fsynced `opened` | One strict fact, no `fenced` | HOLD; no reissue |
| After fsynced `fenced` | Both strict facts; no terminal | HOLD; no reissue |
| Provider reservation before dispatch CAS | One `reserved` budget liability | HOLD; new instance denied |
| Provider after dispatch CAS | One `dispatched` budget liability | HOLD; new instance denied |
| After local `provider.transport.opened` | Physical local transport opened, no settled | HOLD; remote outcome UNKNOWN |
| After local `provider.transport.settled` | Local settled event, budget still dispatched | HOLD; local event is not remote billing ACK |
| FileService after `effect_prepared` | Target unchanged; Tool budget dispatched | HOLD; no causal proof |
| FileService after real `os.replace` | Target changed, only prepared event | HOLD; no second write |
| FileService after `effect_observed` | Target changed, prepared + observed, no committed receipt | HOLD; no causal proof |
| Synthetic finalizer after `run.end` | Budget stopped; no strict terminal | HOLD |
| Synthetic finalizer after strict terminal | Verified zero-effect completed terminal | completed_verified, **never** auto replay |
| Two independent SessionStore workers | One live `run_lease` winner, other denied; SIGKILL releases lock | No concurrent ownership |
| Two independent TaskBudgetStore workers | Same revision CAS, only one reservation committed | One debit, no double spend |
| Operator config rotated between process barrier and next action | Real T1 per-action revocation denies and stops budget | HOLD; no new reservation |

## Trust boundary and deliberate limitations

1. The Provider cases **simulate local events only**. They do not send bytes
   to the remote Provider, prove request acceptance, or resolve the old M4-C
   unsettled liability. Even `provider.transport.settled` is local evidence.
2. The Tool cases use real FileService atomic replacement and an
   **offline synthetic event sink**. They test the physical before/after
   mutation windows but do not establish the real Tool WAL receipt's causal
   link to the exact Tool budget reservation.
3. The finalizer cases write a **synthetic strict terminal** to test the
   existing M5-A reducer. As of this candidate's base, the production
   lifecycle writes ordinary `run.end` fail-open, then seals the budget,
   but **does not yet emit `run.durable.terminal`**. The production
   `run.end` payload also lacks the required `run_generation` join.
   Therefore the positive synthetic completed case is NOT a production
   end-to-end completion proof. A separate minimal runtime terminal
   producer plus independent review and R9 is required before promotion.
4. SIGKILL validates process termination, **not sudden power loss**, fsync
   hardware guarantees, a remote TCP ACK, or every possible instruction
   interleaving. The stage markers establish which code boundary was
   reached; they are test control, not a new recovery source of truth.
5. The active Web recovery view remains read-only, with
   `auto_resume_allowed=false` and `old_run_replay_allowed=false`.
   No queue or SSE path is authorized to start a new Run on its verdict.
6. The old M4-C sample remains `QUARANTINED_UNRESOLVED/HOLD`: one
   Provider liability is unresolved; do not clear, replay, refund or
   overwrite it. Byte SHA-256 must remain
   `94d64a02f2c75edf13e040a11483d478a1d20cd6cc38e4b07563a6a5864590c4`
   (EventStore) and
   `3a0dfa37143e908b8aee4237cbc5745f8f2e298d4c77677de0d1b535de057881`
   (TaskBudgetStore).

## Gates

For this **offline test-only** candidate: targeted tests (including repeat
and cross-process checks), Ruff, Pyright, architecture guard, independent
GLM-5.3 Reviewer `completed/PASS/P0=0/P1=0`, then original full
`bash scripts/ci_gate.sh` real exit 0. Keep original log, exact candidate
SHA/tree/diff SHA and private review receipts.

M5 as a whole remains HOLD for arbitrary automatic recovery until real
runtime terminal producer, authenticated remote Provider settlement, Tool
budget-to-effect causal identity and production entrypoint fault matrix are
separately verified. No GitHub/main/deployment/restart without their own
authorized gates; do not change other parallel worktrees.
