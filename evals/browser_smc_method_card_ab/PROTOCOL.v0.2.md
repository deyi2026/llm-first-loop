# Browser Semantic Operation Compact Method Card A/B — Protocol v0.2

## Question

Does making the provider-agnostic compact Semantic Operation Method Card visible with the Browser SMC capability improve real-model semantic-operation trajectories, without changing Browser execution semantics or granting the program semantic authority?

This protocol is distinct from the closed `browser_smc_method_ab` v0.1 experiment. v0.1 tested whether a stable Method pointer plus MethodStore availability caused the model to hydrate the Method; it did not. v0.2 tests the smaller foundation card itself.

## Frozen treatment

Both arms use the same:

- exact Ornith model/provider contract;
- Browser perception/action runtime and safety boundaries;
- four model-facing tools: `browser_perceive`, `browser_action`, `search_records`, `get_tool_schema`;
- full `method:method-semantic-operation` asset and content hash;
- generic Method discovery/exact-miss semantics;
- tasks, prompts, external-state oracles, iteration/token budgets, fresh session/data/Chrome profile/action ids.

Only the Browser tool descriptions differ:

- `card_off`: frozen pointer-only Browser descriptions from the v0.1 baseline;
- `card_on`: current compact Method Card: `Observe -> Ground -> Scope -> Act -> Receipt -> Verify`, exact Method ref, object/resource mechanical mapping, and `receipt ok != task complete`.

The runner must prove that the raw provider surface SHA differs while a normalized surface with only the two Browser descriptions erased has the same structural SHA. Method availability/hash must be identical in both arms.

## Authority boundary

The treatment may document mechanics. It must not:

- select a task-relevant object;
- silently choose or hydrate a Method;
- auto-latest, retry, replay, rebind, substitute a target, or weaken stale/version checks;
- infer task completion from an ActionReceipt;
- expose selectors, XPath, coordinates, scripts, backend node ids, or CDP methods.

Task success remains an offline deterministic loopback oracle.

## Plan

The plan is 20 paired rows: five tasks x two repeats x two arms. Seed is `2026091305`. The first three task pairs are a six-row smoke:

1. `click_commit`
2. `fill_submit`
3. `delayed_wait`

Each run gets a fresh LFL session/data directory and fresh exact-target Chrome profile. Runs are strictly serial; only one local model server is allowed.

## Frozen smoke gate

The remaining 14 rows run only if all are true after 6/6 smoke rows:

- execution health valid for all rows;
- exact arm surface and no provider fallback;
- both arms adopt SMC in at least 2/3 rows;
- `card_on` produces at least one successful object mutation ActionReceipt;
- `card_on` passes at least one external-state task oracle;
- automatic retry count remains zero;
- frozen old snapshot-scope blocker count remains zero.

Exact Method hydration is measured but is not a gate requirement in v0.2 because the compact card is itself the treatment.

If the gate fails, STOP. Do not change runtime or thresholds and do not run the remaining 14 rows.

## Metrics

Mechanical facts only:

- task oracle result;
- rounds/tool calls/input/output/cache-hit tokens/wall time;
- SMC perceive/action counts;
- Method discovery/exact hydration calls;
- terminal ActionReceipt status and verb;
- object/navigate successful receipts;
- rejection reasons;
- automatic retry and SecurityAgent facts;
- exact/normalized provider surface hashes.

Cache and wall time are descriptive only because the paired rows share one sequential local model server.

## Cross-provider rule

A cloud canary is attempted only if the local v0.2 smoke establishes a usable direction. The exact same Method Card text and semantics must be used; provider-specific rewrites are forbidden. If credentials/runtime are unavailable, report `NOT_QUALIFIED` rather than weakening the local conclusion.
