# SMOKE v0.7-RECOVERY — A+C+E landing verification (6 rows, semantic_execute arm, r=1)

Interventions under test (all landed pre-run, git c42c9043):
- A: invalid_ref rejection now carries executable RECOVERY CONTRACT (perceive→take ref→re-dispatch); no URL exemption, hard boundary kept.
- C: method card gains 3 recovery rules (rejection≠unready / self-caused predicate no-wait / object-level predicate anchoring).
- E: worker emits action_recovery_after_rejection, decided_but_not_dispatched_rounds, partial_only_loop_rounds, object_level_wait_invoked, wait_calls_after_unresolved_rejection.

## Outcome: 2/6 PASS (click_commit 2/2; fill_submit 0/2; delayed_wait 0/2)
All 4 failures ended `max_iterations` at 12 rounds (81–109s wall). No wall-clock TIMEOUT, no partial-checkpoint loops.

## What changed vs v0.6-A2 (mechanically verified)
1. invalid_ref round-1 tax: recovered in 1–2 rounds every time it fired (rows 3,4: action_recovery_after_rejection=1 each; zero wait-on-rejection in r1 rows). Old failure class "reject → wait forever on about:blank" is gone.
2. decide-but-not-dispatch (old rows 4/5, 222 partial ×2): 0 this run. partial_checkpoint_top_repeat=1, peak_tool_draft=1. D-watchdog would not have fired.
3. E-fields now separate failure classes per row (see below).

## Remaining failure classes (post-A+C)
- FC1 navigate args_contract_mismatch: rows 2,3,4 — 1–2 extra rejections each even after get_tool_schema; navigate succeeded only at round ~7–11. Now the dominant round tax on the critical path. Same treatment as A applies: make the args-mismatch receipt carry the expected arg shape for the declared verb.
- FC2 perceptual economy: rows 2,5 — 11–12 browser_perceive calls; fill/click never dispatched. Object located on final round. Not touched by A/C; candidate for B-lane dependency edges or perceive contract budget.
- FC3 scope-family wait trap: row 4 — wait(document_ready_state) satisfied on about:blank, then wait(url) unsatisfied → model self-corrected back to fixing navigate (C-rule-2 worked) but wait_calls_after_unresolved_rejection=2 remains nonzero; object_level_wait_invoked=0 across ALL rows: no run ever organized an object-level wait predicate.

## Verdict
A+C+E mechanically landed and effective on their target failure classes; pass rate unchanged (2/6) because the remaining budget is consumed by FC1/FC2 under a fixed 12-round cap. Next levers: FC1 receipt fix (cheap, same pattern as A), then B/A3 dependency edges for FC2/FC3. Decide round-cap policy explicitly before A3 (recovery contracts legitimately add perceive steps).
