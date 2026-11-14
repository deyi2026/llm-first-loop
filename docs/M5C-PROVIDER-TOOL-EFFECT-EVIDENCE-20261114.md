# M5-C: cross-process Provider/Tool side-effect evidence audit (read-only)

Status: isolated candidate, no merge, no deployment. The auditor is NOT an
admission, settlement, retry, resume, or authorization service.

Parent: M5-B frozen 9c609e9db852ee9019eb182d6c11f4481a3d505d.
M5-A: bd424f0f7d6b9d18284eff3947a073d2aca30483, independent GLM-5.3 PASS
(P0=0/P1=0) and original full R9 exit 0.

## 1. Facts and trust boundary

- The existing EventStore JSONL is the only Provider/Tool event source. It is
  read with the strict raw-file verifier, not ordinary fail-open EventStore.read.
- The existing TaskBudgetStore root is the only budget/reservation authority.
  The auditor captures EventStore, TaskBudgetStore, EventStore, TaskBudgetStore
  again, then rejects identity mismatch or concurrent snapshot drift.
- Provider call.opened is scoped to exact run_generation. Transport opened and
  settled events are joined by exact call_id and attempt_id, with duplicates
  rejected. Settled budget reservations are joined by the exact event_id
  embedded in the existing webt1ev receipt_ref. Foreign-run events are
  accounted separately, never attributed to the target Run.
- Tool effect_prepared and effect_observed are joined by exact execution_id,
  run_generation, canonical path and expected/actual SHA; finished must be
  successful and receipt_committed must carry the same result SHA.
- Provider local receipt references do not authenticate a remote Provider
  request, acceptance, charge or billing settlement. Tool WAL + matching file
  SHA do not establish that this particular execution caused the mutation,
  nor do they link the exact Tool budget reservation to execution_id.
- All reports explicitly set remote_provider_settlement_proven=false,
  tool_effect_causation_proven=false, auto_resume_allowed=false,
  old_run_replay_allowed=false. Decision is always unknown_HOLD. A zero-effect
  report defers to the separate M5-A strict terminal projection; it does not
  grant a new Run.

## 2. Old M4-C frozen sample: real read-only reconciliation

An isolated read-only audit against the old process-crash sample produced:

| Evidence | Observed |
| --- | --- |
| Provider logical calls opened | 3 |
| Provider physical transports opened / locally settled | 3 / 2 |
| Provider physical transport without local settlement | 1 |
| Provider budget reservations not settled | 1 |
| Local Provider receipt event IDs joined | 2 |
| Tool budget invocations / committed WAL receipts | 2 / 2 |
| Tool effect prepared / observed / locally paired | 1 / 1 / 1 |
| Budget phase | closed_uncertain |
| Final decision | unknown_HOLD: provider_unknown_remote_liability |
| Remote settlement or Tool causation proven | false / false |
| Automatic replay or resume permitted | false / false |

Source byte SHA-256 before and after the audit:
- EventStore: 94d64a02f2c75edf13e040a11483d478a1d20cd6cc38e4b07563a6a5864590c4
- TaskBudgetStore: 3a0dfa37143e908b8aee4237cbc5745f8f2e298d4c77677de0d1b535de057881

The original M4-C debt is still QUARANTINED_UNRESOLVED. The audit does not
contact the Provider, clear debt, issue new authorization or touch the target
article. Local private receipt:
data/m5c-effect-audit-20261114/old-m4c-effect-audit.json.

## 3. Known evidence gaps and next work

1. No authenticated remote Provider request/settlement identity. A local
   transport.settled event cannot prove remote billing or acceptance. UNKNOWN
   must remain HOLD.
2. No exact Tool budget reservation_id -> Tool WAL execution_id binding.
   The observed Tool SHA can be reported, not treated as causal proof.
3. The existing Tool WAL event writes may be fail-open. M5-C is read-only and
   does not upgrade their durability or allow replay on missing events.
4. M5-D must expose read-only restart recovery verdicts in Web/SSE/queue
   without dispatching a Run. M5-E must test dual workers, lease/nonce
   revocation, and real SIGKILL at Provider/Tool/finalizer boundaries.

Gate: independent GLM-5.3 completed/PASS P0=P1=0, then original full R9 exit0,
then Host review_admission and GitHub CI/A.5/privacy verification before any
main integration. Managed Mac/Deepin restart requires separate authorization.
