# Evidence Recoverability R7 v2 - Final Result

Date: 2026-08-26
Status: **PASS / REMEDIATION LINE CLOSED**
R7 v1: preserved INVALID due oracle error; not rescored.
A3: STOPPED. Global production EVIDENCE_MODE: unchanged/off.

## Frozen real-provider result

R7 v2 executed the corrected fresh 24-row efficiency holdout under the frozen pack without changing fixtures, runner, scorer or production paths after request #1.

Frozen scorer result: **PASS**.

- 24/24 rows COMPLETED; unresolved infra failures: 0.
- Overall exact: 23/24 (95.83%).
- MiniMax-M3: 11/12 exact (91.67%).
- deepseek-v4-flash: 12/12 exact (100%).
- Q1+Q2 covered fixtures: 11/12 exact.
- Q3 stale-current: 6/6 exact; stale-as-current: 0/6.
- Q4 real coverage-gap control: 6/6 exact.
- transport EvidenceRef used as domain answer: 0.
- exact source+args repeats: 0.
- redundant current-version overlap: 0.
- all frozen contract-path gates: PASS.

The sole non-exact row was R7V2-009 (MiniMax Q1). The model acquired the source exactly once, hydrated the correct Evidence, explicitly reasoned to `LARCH-527`, and the recovery result contained the target. Its final wire text was malformed JSON (`\":\"LARCH-527\"}`), so the frozen exact parser correctly scored it non-exact. This is an output-format miss, not a source-recovery/reacquisition failure.

## Q3 corrected-oracle validation

The staged first real row R7V2-001 (MiniMax Q3) validates why v1 was invalidated and v2 is correct: the model saw `freshness=stale/currentness=historical_only` in the dynamic manifest and immediately performed one legitimate fresh read_file acquisition, then recovered the verified-current Evidence and answered `ASPEN-763`. No stale-as-current behavior, exact repeat or overlap occurred. A later search also reported the old stale ref as blocked; this is diagnostic and is intentionally not a blocking requirement.

## Closure decision

R7 v2 demonstrates the target behavior across both providers: once current source bytes are covered by durable Evidence, providers recover them without repeating exact source calls or reacquiring overlapping ranges; when Q4 exposes a real coverage gap, a non-overlapping source acquisition remains allowed and succeeds. This closes the user-requested remediation line. No R8+ work is part of this closure decision.
