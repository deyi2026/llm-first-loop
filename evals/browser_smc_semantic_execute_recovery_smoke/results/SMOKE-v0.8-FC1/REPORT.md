# SMOKE v0.8-FC1 — deterministic verb-wrapper args normalization (6 rows, semantic_execute arm, r=1)

Only intentional change vs v0.7-RECOVERY (9bf70263 → 53b64ca7):
- FC1 (53b64ca7): compiler-side deterministic verb-wrapper args normalization. Rule: `args == {"<own verb>": {dict}}` → unwrapped verbatim; non-dict wrapper value, multi-key or unknown-key args stay fail-closed. Every action receipt / rejected action gains machine-authored `args_normalization {applied, rule}`. 18 new unit tests; 132 browser/smc tests green.
- Provenance: run at git 2794b2cd, MODEL_REF=cognilocal/ornith-1.5-35b-a3b-mlx (same model v0.7 used; the 8901 short-name alias in f840a0ea made all attempt-1 rows gate-INVALID — that run is discarded, lesson recorded in 2794b2cd). Manifest carries full source_sha256 set, tracked_dirty=false, 6/6 rows gate-VALID.
- Round cap unchanged: max_iterations=12 (main qualification budget kept; 16-round diagnostic ceiling not implemented yet).

## Outcome: 2/6 PASS (fill_submit 2/2; click_commit 0/2; delayed_wait 0/2) — gate FAIL
Composition flipped vs v0.7 (click_commit 2/2→0/2, fill_submit 0/2→2/2): the two runs' pass sets are disjoint.

## What FC1 did (mechanically verified)
1. `args_normalization` receipts present in all 6 rows' trajectories; applied=true fired 4–10×/row on `{"navigate":{"url":...}}`-shaped args.
2. fill_submit rows 2/5: zero rejections, zero recoveries, straight PASS (v0.7: 0/2 with 1–2 args rejections each). Cleanest FC1 win.
3. navigate_ok 5/6 (only the TIMEOUT row has navigate_ok=0).

## New dominant failure class: target_ref field-placement (FC1-family, next field over)
- Rows 1/3/6: invalid_target_ref_failure_count=1 each. Raw evidence (row 1, round 1): `{"verb":"navigate","target_ref":"<bare URL>","args":{"navigate":{"url":"<same URL>"}}}` — args wrapper correctly unwrapped by FC1, but the bare URL sat in target_ref → `target_ref_unavailable:invalid_ref`.
- In all 3 rows the model followed the A-contract receipt (perceive→take ref→re-dispatch) and recovered navigate in-budget (action_recovery_after_rejection=1 each; navigate_ok=1). A contract works on live failures.
- Those rows still ended TASK_FAIL at the object stage (object_ok=0): object-grounding economy, not navigate.
- Same family as FC1 (mechanical placement, not semantic error). Compiler-side deterministic handling vs ref-shape receipt: decision pending.

## Secondary observations
- infra_valid=false is an observation gap, not surface drift: only row 4 (TIMEOUT) wrote no worker-result.json, so its surface_exact defaulted False; the other 5 rows exact. Fix candidate: emit surface status even on timeout.
- rows_object_level_wait_invoked 0→1 (row 3 organized one object-level wait). delayed_wait still 0/2.
- total partial checkpoints 394→265; decided_but_not_dispatched=0, partial_only_loop=0 (D class stays absent; watchdog still would not fire). smc_adoption 6→5.

## Verdict
FC1 round tax is gone (fill_submit 0/2→2/2, zero rejections) — confirms the ruling that mechanically-normalizable errors should not cost model rounds. Remaining 4 failures: 3 rows object-stage grounding economics (FC2 lane) + 1 TIMEOUT. Pass rate stays 2/6 under the kept 12-round cap; disjoint pass sets across v0.7/v0.8 indicate high per-run variance — a repeat and/or the agreed 16-round diagnostic (diagnosis only, never gating) would separate capability vs economy vs variance. Next per ruling: FC2 constrained-semantic-grounding review; A3 dependency edge after.
