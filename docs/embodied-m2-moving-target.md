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
| immediately after the action | epoch / digest | `SCENE_RESET` (all evidence) or `GOAL_CHANGED_MID_ACTION` (that action) |
| at verification | fresh bind, used for `judge_place` | `GOAL_CHANGED_BEFORE_VERIFICATION`, replan |
| duplicate intent | digest at execution vs now | `DUPLICATE_INTENT_STALE_GOAL`, replan |

Every claim is issued by `make_receipt(..., goal_binding=<binding>)`, so the
receipt names the goal. `verify_receipt` / `verify_receipt_fields` /
`ClaimGuard.evaluate_claim` accept `expected_goal_digest`; when supplied, a
missing `goal` block, a block whose digest does not match its own pose
(tamper), or a block for another goal are **all `FAILED_CLAIM`**. A stale goal
is never silently accepted.

`max_goal_rebinds` (default 4) bounds a target that never stops moving; the
episode then terminates `goal_rebind_budget_exhausted` with
`claim_state="hold_unknown"` — never a success.

## Execution state vs verification

`claim_state` is `none` / `pending_oracle` / `hold_unknown`. An action whose
execution state is indeterminate (deadline break, status not `done`) stops the
episode as `hold_unknown_pending_reconciliation` **without** issuing a verdict:
UNKNOWN stays HOLD until a trusted reconciliation decides. `pending_oracle` is
still not success — only a UID463-signed Oracle acceptance can produce
VERIFIED, and that path is unchanged by this issue.

## Evidence

* `tests/embodied_m2/test_moving_target_runner.py` — 7 deterministic fault
  injections on a scripted world: target moves while the model decides, during
  an action, out of band between actions, scene reset mid-episode, duplicate
  intent after a move, indeterminate execution, rebind budget.
* `tests/embodied_m2/test_goal_binding.py` — digest stability/noise, stale
  receipt, missing goal block, tampered block, stale epoch.
* `tests/embodied_m2/test_mujoco_moving_target.py` — real MuJoCo, tray moved
  environment-side (`model.body_pos` + `mj_forward`), real contact physics:
  L3 replan after the move, L4 reset recovery. Includes a discrimination proof:
  the same final snapshot **fails** against the old pose and **passes** against
  the new one.
* `experiments/embodied/m1/calibration/M1-baseline-v1.7.json` — M1 physics
  baseline revalidated under M2 code: 10/10 seeds, deterministic, negatives
  fail-closed. Physics, tolerances, budgets and step counts unchanged.

## Explicitly NOT implemented (M2 infra, disclosed not simulated)

These are out of scope for this slice and are **not** claimed by any test here:

* **Resource contention** (two episodes competing for one MuJoCo instance /
  GPU / model quota).
* **Restart recovery** (process death mid-episode, ledger replay after
  restart). `scene.reset()` is simulated, a process restart is not.
* **Independent stop channel** (out-of-band e-stop that does not travel through
  the same provider/iface path).
* **Real hardware** — none touched.
