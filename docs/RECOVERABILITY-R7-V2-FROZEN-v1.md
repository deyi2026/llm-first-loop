# Evidence Recoverability R7 v2 - Frozen Execution Pack

Date: 2026-08-26
Status: FROZEN BEFORE FIRST R7 v2 REAL PROVIDER REQUEST
R7 v1 remains INVALID; v2 is a fresh corrected holdout, not a rescore.
A3: STOPPED. Global production EVIDENCE_MODE: unchanged/off.

The v2 experiment freezes fresh fixtures/matrix, runner, scorer, tests, corrected pre-registration, provider snapshot and the current production Evidence/source-recovery paths. No treatment/scorer/oracle change is allowed after request #1. The only semantic difference from invalid R7 v1 is that Q3 stale hydration/block is diagnostic rather than required; direct manifest-aware refresh is valid.

Pre-freeze verification: Ruff PASS; Pyright 0/0; R7 v2 tests 6/6 PASS; dry matrix 24/24 exact; dry scorer PASS all blocking gates with exact-repeat=0 and redundant-overlap=0; R0 aggregate 12/12 PASS. Provider snapshot is secret-safe and confirms readiness without recording key values.

Execution discipline: verify artifact hashes and both credentials before request #1; one process-wide runner lock; `.started` crash journal; at most one identical retry for row-level infrastructure failure; first real row is executed alone and inspected before remaining 23.
