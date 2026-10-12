# SMC Browser real-model A/B protocol v0.2

Status: **frozen_not_executed** until this protocol, `PLAN.v0.2.json`, runner sources, and the corrected Browser contract are committed and revalidated.

Supersession: v0.2 does not rewrite or pool `PROTOCOL.v0.1.md`, `PLAN.v0.1.json`, or `results/SMOKE-v0.1/`. The v0.1 smoke remains immutable evidence that the earlier mutation contract exposed a mechanically unusable `snapshot` scope. Browser mutation scope correction is qualified separately in `docs/SMC-BROWSER-PHASE1-MUTATION-SCOPE-CORRECTION-20260913.md`.

## 1. Causal question

Compare the corrected, qualified SMC Browser Phase 1 model surface with the existing legacy Playwright surface while holding LFL harness, Ornith model/server, task prompts, external-state oracles, runtime/sampling configuration, and fresh-run isolation constant.

The treatment is capability shape only:

- SMC arm: `browser_perceive`, `browser_action`, `get_tool_schema`;
- legacy arm: `playwright_exec`, `playwright_test`, `get_tool_schema`.

No prompt names either treatment, selector, XPath, Semantic ID, version scope, or browser implementation. The model remains free to choose among the three visible tools.

## 2. Corrected SMC contract under test

Mutation version scopes are frozen as:

- `click/fill/select/scroll -> object`;
- `navigate -> resource`;
- `snapshot` remains read-only observation/version semantics and is not a mutation precondition scope.

Mandatory fresh pre-dispatch observation, exact identity re-resolution, stale/indeterminate rejection, no retry/replay/rebind/target substitution, and append-only ActionReceipt remain unchanged.

## 3. Tasks and judging

The five deterministic loopback tasks are byte-identical in semantic intent to v0.1: `click_commit`, `fill_submit`, `delayed_wait`, `select_submit`, and `replacement_click`. Task success is determined only by external HTTP fixture state. Duplicate side effects remain visible as counts and are not hidden by a final-state success boolean.

## 4. Plan and isolation

5 tasks × 2 arms × 2 repeats = 20 paired runs. Seed: `2026091302`. Each `(task, repeat)` is one paired block with deterministic within-pair arm order. The first three pair blocks are a six-row smoke prefix: `click_commit/r1`, `fill_submit/r1`, `delayed_wait/r1`.

Every row uses a fresh LFL session, DATA_DIR, Browser Action store, fixture server, and browser profile. Runs are strictly serial because the frozen 8901 server has `prompt-concurrency=1` and `decode-concurrency=1`. A foreign established 8901 client causes refusal rather than contaminated measurement.

## 5. Smoke expansion gate

The remaining 14 rows may run only when all six smoke rows are complete and all of the following are true:

1. no row is `INFRA_FAIL`, `TIMEOUT`, or `INVALID`;
2. no model fallback occurred;
3. every actual provider-facing surface exactly matches its arm allowlist and frozen hash;
4. at least 2/3 SMC rows adopted both Browser perception and action;
5. at least 2/3 legacy rows performed a confirmed physical Playwright execution;
6. the SMC arm produced at least one terminal `ok` ActionReceipt / successful physical dispatch;
7. SMC receipt facts contain zero mutation version-scope blockers (`version_scope_mismatch` or `different_snapshot_same_generation`);
8. at least 1/3 SMC smoke task oracles pass.

Failure of this gate is a valid STOP result. Runtime, prompts, tasks, or thresholds must not be tuned after looking at smoke outcomes.

## 6. Mechanical telemetry

Preserve per-run status and oracle facts, rounds/tool calls, privacy-safe tool argument hashes/shapes, model/fallback/truncation facts, input/output/cache-hit tokens, wall time, exact tool-surface hash/size, SMC terminal receipt status/retry/completeness reasons, legacy confirmed-vs-dry-run calls, and SecurityAgent safety fact.

Report duplicate side effects separately from binary task success. Token/cache metrics are descriptive because the two treatment tool-schema prefixes differ.

## 7. Execution manifest / invalidation

Before the first model call freeze and hash:

- exact git HEAD and clean tracked tree;
- `PROTOCOL.v0.2.md`, `PLAN.v0.2.json`, protocol/runner/worker/scorer/fixture sources;
- corrected Browser Profile/Schema/correction result plus action/perception runtime sources;
- exact provider-facing lazy tool surfaces and hashes;
- task prompt hashes and plan SHA256;
- effective cognilocal provider contract;
- 8901 PID/command/model identity and single-concurrency flags;
- local Playwright package/browser revision used by the legacy arm.

Invalidate rather than reinterpret if tracked HEAD changes mid-matrix, server identity/config drifts, a surface hash changes, a duplicate run directory appears, a foreign 8901 client overlaps a measured start, fallback occurs, or an arm exposes a non-allowlisted tool.

## 8. Interpretation

This is paired directional evidence, not a significance claim. Success, duplicate side effects, hard safety rejections, retry facts, tool/round cost, token/cache facts, and wall time remain separate measurements. v0.1 blocker rows are not pooled into v0.2 statistics.
