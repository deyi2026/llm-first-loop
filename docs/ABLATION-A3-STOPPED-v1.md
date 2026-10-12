# A3 Action-Plane Loop Guard — STOPPED v1

> Status: **STOPPED BY USER — DEVELOPMENT ONLY / NO CONFIRMATORY INTERPRETATION**
> Date: 2026-08-26

## Decision

A3 is stopped because root-cause audit discovered an upstream uncontrolled confound: program-induced evidence recoverability failure across tool-output truncation, history compression, archive retrieval, and provider-specific context projection.

Therefore A3 cannot answer the intended mechanism question cleanly. Action Guard may suppress repeated actions caused by missing evidence without repairing the reason the model repeats them.

## Artifact governance

- `data/calib/runs_a3/A3-001..064.json`: preserve as development evidence; never overwrite or delete.
- A concurrent judging continuation was already in flight when the stop instruction arrived. Any `data/calib/a3_judges/*`, `data/calib/a3_report.json`, or `data/calib/a3_analysis.json` created before/around stop are **stop-race development artifacts only**.
- Do not use those files to claim A3 PASS/FAIL, select a winner, promote a guard, or enter a confirmatory stage.
- Do not resume missing/secondary judging or rerun A3.

## Upstream root cause

See `docs/PROGRAM-INDUCED-DRIFT-ROOT-CAUSE-v1.md`.

Before any fresh action-guard benchmark, first establish a Recoverability Contract: capture full observations before projection, stable evidence refs across rebuilds/providers, exact AI hydration by ref, durable evidence ledger, and repaired discovery semantics.
