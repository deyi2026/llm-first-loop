# Browser SMC Semantic Operation Method A/B v0.1

## Question

Does the same provider-agnostic `method:method-semantic-operation` improve a
model's use of the already-qualified Browser Phase 1 SMC surface without
changing Browser runtime semantics or adding programmatic strategy authority?

## Single variable

Both arms expose the exact same four tools and exact same provider-visible tool
schemas/descriptions:

- `browser_perceive`
- `browser_action`
- `search_records`
- `get_tool_schema`

Both descriptions contain the same optional exact Method pointer.  The only
treatment variable is MethodStore availability:

- `method_off`: a fresh empty `METHOD_SEED_DIR`; exact Method hydration returns
  no record.
- `method_on`: the committed reviewed seed directory; exact hydration of
  `method:method-semantic-operation` returns the frozen Method bytes.

Runtime `METHODS_DIR` is fresh per row in both arms.  There is no automatic
Method injection, no prompt wrapper, and no provider-specific Method wording.

## Runtime contract

Same model/provider/settings, task prompt, Browser runtime, loopback fixture,
Chrome launch policy and SMC capability surface per pair.  Fresh LFL session,
data dir, Chrome profile and action receipt store per row.  Runs are strictly
serial and the controller refuses a measured row when port 8901 has another
established client.

The experiment does not alter stale/version/identity semantics, auto-retry,
rebind, target choice, or task-completion logic.  `METHOD_REFLECTION_MODE=off`.

## Plan

Five deterministic tasks × two repeats × two arms = 20 rows.  The first three
task pairs (`click_commit`, `fill_submit`, `delayed_wait`) are the six-row smoke.
Only a passing frozen smoke gate permits the remaining 14 rows.

Each controller invocation may execute at most one new row.

## Smoke expansion gate

All must hold:

1. 6/6 rows complete with valid execution health, exact surface and no fallback.
2. Method ON exact-hydrates the frozen Method in at least 2/3 rows; OFF hydrates
   it in 0 rows.
3. Both arms actually adopt SMC (`browser_perceive` + `browser_action`) in at
   least 2/3 rows.
4. Method ON produces at least one successful object mutation receipt and at
   least one task-oracle PASS.
5. Automatic retry remains zero and the old snapshot-scope blocker remains zero.

If the gate fails, STOP.  Do not tune Browser runtime, task prompts, Method
content or thresholds after observing the smoke.

## Scoring

Mechanical/offline only:

- external-state task oracle;
- Method discovery/exact-hydration calls;
- SMC adoption and action/perception sequence;
- terminal ActionReceipt status/verb/rejection reason;
- successful object mutations vs navigation;
- automatic retry and old scope blockers;
- rounds/tool calls/input/output/cache-hit tokens/wall time.

A safety rejection is recorded as a mechanical fact, not automatically called a
model semantic failure.  Cache/wall-time metrics are descriptive unless the
execution ordering supports stronger attribution.

## Non-claims

This protocol does not claim cloud-provider parity, statistical significance,
Phase 2 vision/native UI support, root-level scroll support, or that Method
hydration proves the model applied the Method.
