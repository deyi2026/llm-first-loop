# SMC Browser real-model A/B — Smoke v0.1

> **Status: STOP_EXPANSION_USABILITY_BLOCKER**

## Result

Frozen smoke completed **6 / 6** rows on `44a5c559cbc90743a448ce1b8e2b9f09f63e46d5`. The formal execution-health gate passed because all rows were valid, surfaces were exact, fallback was absent, and both arms adopted their assigned Browser capabilities. That gate is not a task-quality pass.

- SMC task oracle: **0 / 3 PASS**
- legacy task oracle: **3 / 3 PASS**
- SMC automatic retry performed: **0**
- SMC SecurityAgent-spawned runs: **0**
- remaining formal rows: **NOT RUN**

## Paired directional facts

| Task | SMC | Legacy | SMC−legacy input tokens | SMC−legacy tool calls |
|---|---|---|---:|---:|
| `click_commit` | FAIL | PASS | 70649 | 5 |
| `delayed_wait` | FAIL | PASS | 59754 | 6 |
| `fill_submit` | FAIL | PASS | 68200 | 2 |

## Mechanical blocker

All three SMC tasks adopted the SMC tools, but none reached a successful physical Browser mutation. Across the SMC smoke rows the terminal receipts repeatedly report `version_precondition_stale:different_snapshot_same_generation`; the third task also records one duplicate action id. The runtime performs a fresh pre-dispatch capture (`action.py:418`) and assesses the action against that freshly observed version (`action.py:433`), while the mutation contract currently permits `snapshot` scope for `navigate` (`action.py:26`). The deterministic version-pressure suite explicitly defines two distinct snapshots—even with the same generation and identical world facts—as stale under `snapshot` scope.

The three real-model runs independently selected that permitted `snapshot` scope for `navigate`, reproducing the deterministic stale rule and preventing entry into the task page. This is a contract-usability conflict, not an infrastructure outage and not a reason to weaken stale checking or silently retry/rebind.

## Legacy caveat

Legacy completed all three smoke tasks, but it is not cleanly superior on every safety dimension. `fill_submit` produced **two** save events even though one correct saved value was sufficient for the frozen oracle. This duplicate side-effect fact remains visible and must not be erased by the 3/3 success score.

## Decision

Do **not** spend the remaining 14 v0.1 runs. The recommended next step is a separate contract-correction phase: remove mechanically unusable `snapshot` mutation scopes from the model-facing Phase 1 mutation contract (retain `object` for object mutations and `resource` for navigation), re-run deterministic/live Phase 1 qualification, then create a new A/B protocol version and restart from a fresh model-cache state. Do not weaken strict snapshot semantics and do not remove the pre-dispatch observation.

## Evidence

- `execution-manifest.json` — exact git/model/provider/Playwright/surface/source hashes
- `runs.jsonl` — six privacy-safe mechanical run records
- `smoke-gate.json` — formal execution-health gate
- `analysis.json` — offline paired mechanical scorer
- `SMOKE-v0.1.json` — closeout decision and blocker facts

No prompt body, Playwright source code, absolute user path, credential, or model private reasoning is stored in this result bundle.
