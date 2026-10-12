# Evidence Recoverability R10 — Physical Source Resolution Provider Result v1

Date: 2026-08-26
Status: **PASS / SEALED**
A3: STOPPED
Production Evidence activation: unchanged/off

## Frozen real-provider result

24/24 rows completed with no unresolved infra.

- exact answer: **24/24**
  - MiniMax: 12/12
  - DeepSeek: 12/12
- transport EvidenceRef used as domain answer: 0
- stale-as-current: 0
- physical exact same-source+args repeat: 0
- physical redundant overlap: 0
- model-declared successful read_file calls: 24
- physical source executions: 24
- Evidence-reuse source resolutions: 0

Every correctness/currentness/coverage/path gate in the frozen scorer passed.

The real R10 sample did not randomly reproduce R8's provider behavior of precommitting a redundant source fallback in the same tool batch; each row declared exactly one read_file. Therefore R10 primarily confirms that R9 does not suppress legitimate fresh reads, stale refreshes, or real coverage-gap acquisition.

## Exact historical-behavior counterfactual

To confirm the R8 failure mechanism itself, the two actual DeepSeek overlap rows `R8-006` and `R8-011` were replayed offline through R9 using their original real-provider declarations:

Historical declaration pattern in each case:

1. round1 full `read_file`;
2. round2 `search_evidence(target)` + overlapping `read_file` fallback in the same assistant tool batch.

Historical R8 outcome per row:

- declared read_file: 2
- physical-read proxy: 2
- redundant overlap: 1

R9 counterfactual outcome per row with the same declarations:

- first read: `source_execution`
- search: success, target hit
- fallback: `evidence_reuse`
- fallback physical execution: false
- fallback EvidenceRef equals first EvidenceRef
- physical source executions: 1
- Evidence reuses: 1
- ledger records: 1

Counterfactual report: **2/2 PASS**.

This establishes the R9 mechanism on the exact provider behavior that caused R8's failure, while R10 independently confirms no regression on fresh real-provider currentness/coverage tasks.

## Interpretation

R9/R10 resolve the program-level source reacquisition problem without relying on provider parallel-tool controls and without dropping any tool declaration. If a provider precommits a covered FILE fallback, standard protocol pairing is preserved but the fallback becomes a small Evidence-reuse result instead of source I/O + a new EvidenceRecord.

A provider-declared fallback can still add an assistant tool-call entry and a small tool result to conversation suffix. That is a separate model/protocol efficiency concern, not a physical source-recovery failure. The next phase should measure long-session prompt/compression/cache behavior rather than add another anti-repeat rule.
