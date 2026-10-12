# Evidence Recoverability R7 v1 — Invalidated Holdout

Date: 2026-08-26
Status: **INVALIDATED AFTER FIRST REAL ROW; NO BEHAVIORAL FAIL INFERRED**
Rows executed: **1/24** (`R7-001`, MiniMax Q3)
Remaining rows: **not executed**

## Why invalidated

The pre-registered Q3 path gate required every exact stale-current row to produce at least one `stale_block_count` before refreshing the source. The first real row demonstrated a strictly better valid path:

1. provider sees the dynamic Recovery Manifest before its first request;
2. manifest explicitly marks the pre-acquired Evidence `freshness=stale` and `currentness=historical_only`;
3. model correctly reasons that the task asks for CURRENT state and therefore does **not** attempt to hydrate stale Evidence;
4. model performs exactly one fresh `read_file` acquisition;
5. the new Evidence is `verified_current/current`;
6. model uses `read_evidence` and returns exact `PLUM-842`.

Mechanical row result:

- status `COMPLETED`;
- exact answer `true`;
- model source execution `1`;
- exact source+args repeat `0`;
- redundant overlap `0`;
- stale-as-current `false`;
- recovery answer hit `1`;
- stale block `0`.

Requiring a failed stale hydration is therefore an oracle error: it penalizes a model for correctly consuming the stale/currentness metadata already present in the manifest. It also conflicts with the R7 efficiency objective.

## Integrity decision

The frozen v1 scorer is not modified and the remaining matrix is not run. R7 v1 is not scored as provider/R6 FAIL. A new holdout must use fresh unseen fixture bytes/tokens and replace the invalid path condition with the behaviorally correct invariant:

> for stale CURRENT tasks, stale-as-current must be zero and exactly one legitimate fresh source acquisition must occur before an exact answer; an attempted stale hydration/block is optional diagnostic behavior, not a gate.

All other overlap/repeat/currentness principles remain unchanged.
