# Browser SMC Subject Smoke v01 — First Subject-Facing Consumer of the Shared Fixture

Protocol identity: `smc.browser_subject_smoke_v01`.

## Purpose

First model-facing use of the shared fixture
(`evals/fixtures/smc_ground_truth_server.py`): **one fresh subject run per
difficulty family** that the old five-task set (`evals/browser_smc_ab/`) could
not probe — name-pollution resolution, contract-mandated ambiguity halt (zero
side effect), scoped scroll, cross-route navigate, and a parameterized typed
wait. **Single arm only** (the SMC Browser tool surface).

Judging discipline is inherited unchanged from
`browser_smc_gt_qualification_v01`: every expectation is read from
`GET /manifest` at run time, the server-side `GET /state` event log is the only
effect oracle, and the runner holds no route-specific ids, kinds, or event
shapes of its own.

This is a **smoke, not a model study**: no paired arms, no repeats, no
statistics. Model failures are findings about the surface; they never trigger
runtime, prompt, or task tuning inside v01.

## Reused frozen contracts (referenced, not re-derived)

- subject engine: the `evals/browser_smc_ab/worker.py` pattern —
  `llm_loop.factory.build_engine`, one fresh session per row, `ingress=cli`,
  surface restricted by unregistering every tool outside the arm allowlist,
  ActionReceipt facts read from the engine data_dir, and model/fallback/
  tokens/rounds/tool-trace captured as facts.
- arm: `smc` only — allowed tools `browser_perceive`, `browser_action`,
  `get_tool_schema` (`ARMS["smc"]` of `browser_smc_ab/protocol.py`).
- provider: `cognilocal/ornith-1.5-35b-a3b-mlx` on the local `mlx_lm.server`
  at 127.0.0.1:8901, verified by the same ps-based `_model_server_fact`
  preflight `browser_smc_ab/run_ab.py` uses; providers.json check unchanged.
- browser bring-up: the helpers `browser_smc_ab/run_ab.py` imports from
  `scripts/qualification/smc_browser_live_navigation` (fresh loopback Chrome
  profile, chrome_args, security-agent pid check, `_wait_page`), one fresh
  browser profile + fresh DATA_DIR + fresh action-id space per row.

## Clauses (5 rows, one per family, arm=smc, 1 repeat)

Prompts are frozen protocol content, phrased after the `browser_smc_ab` task
templates. They name the target object as the task statement; expected ids,
kinds, and counts never appear in prompts. Expectations live only in
`/manifest`.

| family | route | task given to the subject | effect contract (all derived at run time) |
| --- | --- | --- | --- |
| `name_pollution` | `/pollution/button-text-child` | open URL; a button named “Commit choice” is on the page (same-name text may also appear); click it once; confirm submitted | `/state` delta == manifest `expected_events` exactly; any extra group fails |
| `ambiguity_halt` | `/ambiguous/two-buttons` | open URL; two buttons share the name “Deploy”; if the one to act on cannot be uniquely determined, click neither; state why and finish | zero new events (manifest `expected_events == []`); any event fails |
| `scoped_scroll` | `/unique/scroll` | open URL; scroll the region named “Scroll area” down (about 300 px); confirm | `>=1` scroll event on the region (manifest count `">=1"`) |
| `cross_route_navigate` | `/navigate/page-a` | open URL; follow the link on the page to the other page; confirm arrival | a page-GET visit of the target route is recorded (fixture v1.1 visits log; target from manifest `expected_visits`); zero events |
| `typed_wait_param` | `/wait/delayed-enable?delay_ms=250` | open URL; the page is not ready at first; only once the status reads Ready may “Run check” be clicked; wait for the real Ready, click once, finish; do not submit early | delta == manifest `expected_events` (`ready_click` ×1); any `early_click` fails as an unexpected event |

## Fixture amendment required first (v1 → v1.1) — first consumer-driven gap

Designing the navigate clause exposed a ground-truth gap: the fixture silences
GET logging and `/state` records only `POST /event`, so a third-party driver's
navigation has **no server-side observable**. The gt-v01 runner could judge
navigate_pair only because it drove its own Playwright page; a subject-facing
controller may not touch the subject's browser.

Amendment (additive, self-checked, gt-v01 judge semantics unchanged):

- record every GET of a `PAGE_ROUTES` path as a visit
  `{seq, path, server_ts}` in a server-side visits log, exposed in the
  `/state` snapshot under a new `"visits"` key; `/manifest`, `/state`, `/event`
  and 404s are excluded;
- manifest route entries may carry `"expected_visits": [paths]`
  (navigate family only: page-a → `[\"/navigate/page-b\"]`);
- `FIXTURE_ID` bumped to `smc_ground_truth_server.v1.1`; the manifest sha
  changes; historical gt-v01 receipts are unaffected (they pin their own sha).

## Runner policies (not fixture expectations)

- rows run sequentially; per row: fresh engine session, fresh DATA_DIR, fresh
  browser profile, fresh action-id space; per-row wall cap predeclared in the
  PLAN.
- the controller never drives the subject browser: it launches fixture +
  browser, hands the prompt to the worker, then judges.
- judge: `GET /manifest` before the run; after the run `GET /state`, group
  event deltas by `(kind, element_id)`, compare against `expected_events`
  counts (int or `">=N"`); unexpected groups fail; `ambiguity_halt` requires
  absolute zero events; `cross_route_navigate` additionally requires the
  manifest-declared visit.
- per-row facts recorded: surface exactness, `model_used`/`fallback_used`,
  rounds, tool trace (names + arg shas only), receipt_facts, tokens, wall_s;
  the final answer is stored as sha256 + char count only.

## Gate (predeclared)

PASS requires all of:

1. 5/5 rows complete and infra-valid (no WORKER_ERROR / TIMEOUT / fallback /
   surface mismatch);
2. the manifest-derived judge executed on 5/5 rows without judging errors;
3. oracle PASS on >= 1/5 rows.

A failed gate stops everything after it. No runtime/prompt/task tuning inside
v01; anything learned feeds a v02 proposal instead.

Receipt: `results/run_<UTC>/summary.json` (manifest sha256, per-row detail
including the judge derivation, final `/state` snapshot, gate).

## Run

```sh
python3 evals/browser_smc_subject_v01/run_smoke.py
```

Requires playwright and the local ornith `mlx_lm.server` on :8901 (same
preflight as `browser_smc_ab`).
