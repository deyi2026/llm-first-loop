# Evidence Recoverability R8 — Frozen Clean Efficiency Holdout v1

Date: 2026-08-26
Status: **FROZEN BEFORE FIRST R8 REAL PROVIDER REQUEST**
Providers: MiniMax `MiniMax-M3`, DeepSeek `deepseek-v4-flash`
A3: STOPPED
Production activation: unchanged/off

R8 is the clean replacement for invalidated R7 v1. It retains the same source-overlap question with new unseen fixtures/tokens, but removes the invalid requirement that a model must first attempt stale hydration even when the Recovery Manifest already marks Evidence stale/historical_only.

Frozen matrix: 24 rows, 2 providers × P1..P4 × 3 reps, seed 20260826.

Frozen behavioral contract:
- covered current bytes/results -> recover Evidence instead of overlapping source reacquisition;
- stale CURRENT task -> exactly one legitimate fresh source acquisition is sufficient; stale hydration attempt is optional;
- real coverage gap -> non-overlapping source acquisition is legitimate;
- no Action Guard, duplicate suppression or post-hoc scorer changes.

Pre-real verification: R8 tests PASS, R6/R3 focused PASS, Ruff PASS, Pyright 0/0, dry 24/24 exact with repeat=0/overlap=0, dry scorer PASS all gates, R0 12/12 PASS, both provider credentials present.
