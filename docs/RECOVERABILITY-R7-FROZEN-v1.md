# Evidence Recoverability R7 — Frozen Efficiency Holdout v1

Date: 2026-08-26
Status: **FROZEN BEFORE FIRST R7 REAL PROVIDER REQUEST**
Providers: MiniMax `MiniMax-M3`, DeepSeek `deepseek-v4-flash`
A3: **STOPPED**
Production activation: **unchanged / off**

## Frozen question

Does the R6 source-vs-recovery contract remove redundant overlapping `read_file` acquisition after bytes are already covered by durable Evidence, without suppressing a legitimate non-overlapping acquisition when coverage is missing?

## Matrix

- 24 fresh runs: 2 providers × Q1..Q4 × 3 reps.
- fixed seed `20260826`.
- Q1/Q2: first full source acquisition must be followed by recovery, not overlapping reacquisition.
- Q3: stale pre-acquired Evidence requires one legitimate current refresh; after refresh, covered content is recovered.
- Q4: current precoverage `[0,60)` plus target hint `[100,160)` requires legitimate non-overlapping coverage-gap acquisition.

## Frozen mechanics

The runner uses production `ReadFileTool`, `ToolRegistry`, `EvidenceEnforcer`, R3 recovery tools/freshness/manifest, and the R6 model-facing description. It does not add Action Guard or intercept source calls. Exact-repeat and overlap metrics are observational.

Process safety retains the R5/R4 discipline: process-wide runner lock, atomic `.started` row journal, atomic result, and at most one identical retry only for `INFRA_FAILURE`.

## Frozen gates

The blocking gates are exactly those in `docs/RECOVERABILITY-R7-PRE-REGISTRATION-v1.md` and `scripts/evidence/r7/score.py`; scorer changes after real request #1 are forbidden except an explicitly documented infra-only amendment that cannot change fixtures, behavioral prompts, metrics, thresholds, or production code.

## Pre-real verification

Before freeze:

- R7 unit tests: PASS.
- R6/R3 focused tests: PASS.
- Ruff: PASS.
- Pyright: 0 errors / 0 warnings.
- dry matrix: 24/24 exact; exact-repeat=0; overlap=0.
- dry scorer: PASS all gates.
- R0 aggregate: 12/12 PASS.
- provider snapshot: both required credentials present.
- real result directory: empty.
- active R7 runner: none.

The machine lock `tests/fixtures/evidence_r7/frozen_v1.json` is generated after this document and is verified before every real runner invocation.
