# Evidence Recoverability R7 v2 - Corrected Efficiency Holdout Pre-Registration

Date: 2026-08-26
Status: PRE-REGISTERED BEFORE ANY R7 v2 PROVIDER REQUEST
Supersedes only the invalid R7 v1 oracle; production code is unchanged.
A3: STOPPED. Production EVIDENCE_MODE: unchanged/off.

## Why v2 exists
R7 v1 was invalidated after one real row because Q3 incorrectly required a stale hydration/block. A provider that reads `freshness=stale currentness=historical_only` from the Recovery Manifest and directly performs one legitimate current-source refresh is strictly correct and more efficient. R7 v2 removes only that invalid requirement and uses fresh unseen bytes/tokens.

## Fresh fixtures
- Q1 full-covered current: `R7V2-PRIMARY-TARGET: LARCH-527`.
- Q2 full-covered current: `R7V2-SECONDARY-TARGET: PEARL-681`.
- Q3 stale full evidence mutates `CLOVE-214 -> ASPEN-763`; task asks CURRENT.
- Q4 current partial coverage `[0,60)` with target `R7V2-GAP-TARGET: TOPAZ-438` in `[100,160)`.

## Matrix
2 providers x 4 seeds x 3 reps = 24 rows; fixed shuffle seed 20260826; fresh owner/store/conversation each row.

## Blocking gates
1. 24/24 COMPLETED; freeze verified; single-runner/crash journal integrity.
2. transport EvidenceRef as business answer = 0.
3. exact source+args repeats = 0.
4. redundant current-version overlap = 0.
5. Q3 stale-as-current = 0.
6. overall exact >=22/24; each provider >=10/12.
7. Q1+Q2 exact >=11/12 and each provider >=5/6; every exact row has exactly one source acquisition and recovery answer hit.
8. Q3 exact >=5/6 and each provider >=2/3; every exact row has exactly one legitimate post-change source acquisition and later recovery answer hit. Stale hydration/block is diagnostic only.
9. Q4 exact >=5/6 and each provider >=2/3; exact rows must acquire uncovered source range, have zero overlap, and recovery answer hit.

PASS closes the R7 remediation line per user instruction. No R8+ work is part of this run.
