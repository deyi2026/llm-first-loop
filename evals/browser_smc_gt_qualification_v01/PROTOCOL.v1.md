# Browser SMC Ground-Truth Qualification v01 — First Consumer of the Shared Fixture

Protocol identity: `smc.browser_gt_qualification_v01`.

## Purpose

Qualify the shared fixture (`evals/fixtures/smc_ground_truth_server.py`) as
usable ground truth, by being its first consumer: a runner that executes one
clause per route family and whose **every expectation comes from
`GET /manifest`**, with the **server-side `GET /state` event log as the only
effect oracle**. The runner contains no route-specific names, ids, or event
shapes.

This is explicitly **not** a model study: no worker, no provider, no frozen
prompts, no per-eval `fixture_server.py` copy. The nine frozen
`evals/browser_smc_*` protocol identities stay untouched. Future
subject-facing qualifications should reuse this pattern: launch the shared
fixture, drive the subject, judge strictly against `/manifest` + `/state`.

## Clauses

| family | routes | contract |
| --- | --- | --- |
| `index` | `/` | manifest marker present; every other route linked |
| `dispatch` | `/unique/*`, `/htmx/click` | grounding count == `kind_name_matches`; act on the object whose kind matches `expected_events[0].kind`; confirm via remaining canonical buttons; delta events must equal `expected_events` exactly (no extras) |
| `grounding_probe` | `/pollution/button-text-child` | kind+name resolves to `kind_name_matches`; raw CDP AX same-name occurrences satisfy `name_only_matches`; then dispatch |
| `halt` | `/ambiguous/two-buttons` | kind+name count == 2; **no action**; zero new events (contract-mandated halt, zero side effect) |
| `wait_then_dispatch` | `/wait/delayed-enable?delay_ms=250` | actionability wait precedes the single mutation; delta == `expected_events`; any `early_click` fails as an unexpected event |
| `wait_observe` | `/wait/delayed-appear?delay_ms=250` | canonical object absent at load becomes visible; zero events |
| `navigate_pair` | `/navigate/page-a` -> `/navigate/page-b` | follow the cross-route link; landing page carries the target manifest marker; zero events |

## Runner policies (not fixture expectations)

- kind -> locator mapping is protocol policy: `button` -> role+exact name
  (the FC2-B kind+name path); `input|select|div` -> `[aria-label=...]`;
  `region` -> role.
- fill value is the constant `qual-v01`; select picks the last `<option>`
  at run time; scroll sets `scrollTop=300` and settles 400ms.
- effect oracle groups `/state` deltas by `(kind, element_id)` and compares
  against `expected_events` counts (int or `">=N"`); unexpected groups fail.

## Gate

All clauses pass -> exit 0. Receipt: `results/run_<UTC>/summary.json`
(manifest sha256, per-clause detail, final `/state` snapshot).

## Run

```sh
python3 evals/browser_smc_gt_qualification_v01/run_qualification.py
```

Requires playwright. HTTP-level fixture self-check and browser smoke live in
`evals/fixtures/` (see its README).
