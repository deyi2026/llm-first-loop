# Embodied M2 — moving-target replanning with fresh Oracle goal binding

Issue: #79 (`feat(embodied-m2): moving-target replanning with fresh Oracle goal binding`)
Lane: `feat/embodied-m2-moving-target-20261120` · base `1fca1fa75` (PR #84 merge)

## Defect (M1)

`run_episode` bound the goal once, before the action loop:

```python
tray = scene.observe()["tray_pos"]      # cached for the whole episode
...
ok, ev = judge_place(snap, tray)        # judged against the cached pose
```

A tray that moves makes that cached pose a **different goal**. Two failure
modes follow: a real place is rejected forever (stale goal), or a place is
"verified" against a pose the cube never reached (goal drift + luck). The
receipt carried only `scene_epoch`, so nothing in the evidence said *which*
goal the claim was about.

## Change

`goal_binding.py` (new) defines a **GoalBinding**: canonical pose (1e-6 m),
`sha256(kind, pos)` digest, `scene_epoch`, and a monotonic `version`.

`run_episode` re-observes the target and epoch at four points:

| point | check | on change |
|---|---|---|
| before each decision | epoch / digest vs baseline | invalidate claims, rebind, replan |
| immediately after the action | epoch / digest | `SCENE_RESET` (all evidence) or `GOAL_CHANGED_MID_ACTION` (that action: kept visible, tagged with the goal it ran against) |
| at verification | fresh bind, used for `judge_place` | `GOAL_CHANGED_BEFORE_VERIFICATION`, replan |
| duplicate intent | digest **and epoch** at execution vs now | `DUPLICATE_INTENT_STALE_GOAL`, replan |

Every claim is issued by `make_receipt(..., goal_binding=<binding>)`, so the
receipt names the goal. `verify_receipt` / `verify_receipt_fields` /
`ClaimGuard.evaluate_claim` accept `expected_goal_digest`. A `goal` block is
validated **whenever it is present**: a digest that does not match its own pose
(tamper), a block epoch that disagrees with the receipt, or a block for another
goal are `FAILED_CLAIM` even if the caller passed no expectation. When the
caller *does* supply an expectation, a missing block is `FAILED_CLAIM` too;
`run_episode` always supplies it, so the in-episode path is fail-closed. A
receipt with no block and no expectation keeps the legacy M1 rule
(epoch + verdict only) so already-frozen M1 receipts keep their meaning. A stale
goal is never silently accepted on the M2 path.

`max_goal_rebinds` (default 4) bounds a target that never stops moving; the
episode then terminates `goal_rebind_budget_exhausted` with
`claim_state="hold_unknown"` — never a success. `max_provider_attempts`
counts **every** `provider.decide` call (M1 counted only provider exceptions),
so the budget now also bounds invalid-decision loops.

## Execution state vs verification

`claim_state` is `none` / `pending_oracle` / `hold_unknown`. An action whose
execution state is indeterminate (deadline break, status not `done`) stops the
episode as `hold_unknown_pending_reconciliation` **without** issuing a verdict:
UNKNOWN stays HOLD until a trusted reconciliation decides. Indeterminate
execution takes precedence over a concurrent goal change — if the target moves
in the same settle window, the episode still holds, because replanning away an
unreconciled action would let a later claim cover it up. `pending_oracle` is
still not success — only a UID463-signed Oracle acceptance can produce
VERIFIED, and that path is unchanged by this issue.

## Evidence

* `tests/embodied_m2/test_moving_target_runner.py` — 12 deterministic
  scenarios on a scripted world: target moves while the model decides, during
  an action (the voided action stays visible, tagged with the goal it ran
  against), out of band between actions, while `release` settles before
  verification, scene reset mid-episode, scene reset with the **same pose** then a
  replay of the previous epoch's intent (stale, not absorbed), duplicate intent
  after a move, indeterminate execution, indeterminate execution **plus** a
  concurrent move (HOLD wins), replay of a voided action (stale-duplicate, not
  absorbed), rebind budget, and the M1 `t_s` trace regression.
  Duplicate detection is per episode: a replay carried over from a previous
  episode is not attributed to the new goal, and this slice does not emit an
  event for it.
* `tests/embodied_m2/test_goal_binding.py` — digest stability/noise, stale
  receipt, missing goal block, tampered block, stale epoch, a tampered block
  with **no** expected digest (the absent expectation is not a bypass), a goal
  block whose epoch disagrees with the receipt, and a receipt that names a goal
  the action did not run against (`RECEIPT_GOAL_MISMATCH` → hold).
* `tests/embodied_m2/harness.py` keeps the cube on the tray, so the scripted
  scenarios prove event and binding semantics; geometric discrimination against
  an old pose is proven only by the MuJoCo module below, not by the scripted
  world.
* `tests/embodied_m2/test_mujoco_moving_target.py` — real MuJoCo, tray moved
  environment-side (`model.body_pos` + `mj_forward`), real contact physics:
  L3 replan after the move, L4 reset recovery. Includes a discrimination proof:
  the same final snapshot **fails** against the old pose and **passes** against
  the new one.
* `experiments/embodied/m1/calibration/M1-baseline-v1.8.json` and
  `M1-baseline-v1.9.json` — M1 physics baseline revalidated under M2 code:
  10/10 seeds, deterministic, negatives fail-closed. Physics, tolerances,
  budgets and step counts unchanged (v1.7 stays frozen for QA; v1.8 records the
  first M2 pass, v1.9 the code after the second review round's fixes).

## Explicitly NOT implemented (M2 infra, disclosed not simulated)

These are out of scope for this slice and are **not** claimed by any test here:

* **Resource contention** (two episodes competing for one MuJoCo instance /
  GPU / model quota).
* **Restart recovery** (process death mid-episode, ledger replay after
  restart). `scene.reset()` is simulated, a process restart is not.
* **Independent stop channel** (out-of-band e-stop that does not travel through
  the same provider/iface path).
* **Real hardware** — none touched.
