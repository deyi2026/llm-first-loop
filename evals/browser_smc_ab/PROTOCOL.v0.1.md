# SMC Browser real-model A/B protocol v0.1

Status: **frozen-before-model-execution candidate**. This protocol must be committed on a clean tracked tree before the first measured model call.

## 1. Causal question

Compare the already-qualified SMC Browser Phase 1 model surface with LFL's current legacy Playwright model surface while holding the LFL harness, Ornith weights/server, task prompt, external-state judge, sampling/runtime configuration, and run isolation constant.

The treatment is capability representation, not an appended instruction. Task prompts never name either tool family.

## 2. Arms

- `smc`: exactly `browser_perceive`, `browser_action`, `get_tool_schema`.
- `legacy`: exactly `playwright_exec`, `playwright_test`, `get_tool_schema`.

The engine is built normally, then every non-allowlisted tool is unregistered before the model sees schemas. This deliberately removes `execute_command`, web tools, subagents and other bypasses from **both** arms. `RUN_MODE=ptc` is not used because it would also hide unrelated web tools and confound the treatment.

SMC uses one exact loopback CDP target and persistent fresh-profile Chrome for that run. Legacy Playwright retains its production behavior: each physical call starts its own isolated browser process. That difference is part of the current capability design being measured.

## 3. Fixed model/runtime

- model ref: `cognilocal/ornith-1.5-35b-a3b-mlx`
- local endpoint: 8901, single prompt/decode concurrency required by execution manifest
- thinking: on; effort: medium
- temperature/model sampling: provider registry value (currently deterministic temperature 0.0)
- max iterations: 12
- model timeout: 90 s/request
- max output: 4096 tokens
- tool schema lazy: on
- model fallbacks: disabled
- extraction: disabled
- summary: off
- method reflection: off
- legacy environment precondition: Playwright Python `1.58.0`, Chromium revision `1208`, and the matching headless shell are present in the experiment interpreter environment. This environment-only repair is frozen in the execution manifest and does not change legacy tool semantics.

Only one measured model run may use 8901 at a time. A run refuses to start while an unrelated established 8901 client exists. No second local model may be loaded.

## 4. Five deterministic tasks

All pages are served by a fresh loopback-only `ThreadingHTTPServer`. The judge reads server-side state; model prose is never a success oracle.

| task | required external state |
|---|---|
| `click_commit` | exactly one commit event |
| `fill_submit` | saved Project code exactly `AB-7319` |
| `delayed_wait` | one post-Ready click and zero early click |
| `select_submit` | saved Region exactly `west` |
| `replacement_click` | zero generation-1 Deploy clicks and exactly one generation-2 click |

Every run receives a fresh server state, fresh LFL session/data dir, and—on SMC—a fresh Chrome profile/target. No result/session/browser state is shared across arms.

## 5. Frozen 20-run paired plan

Seed: `20260913`.

Frozen plan SHA256: `109e705ef9e011a1de30f75002096749d8ba997203614f319086ec0564062689`.

There are 5 tasks × 2 arms × 2 repeats = 20 runs. Each `(task, repeat)` is a pair block; arm order inside a pair is deterministically shuffled. The first three pair blocks form a six-run smoke prefix: `click_commit/r1`, `fill_submit/r1`, `delayed_wait/r1`.

The generated plan and its SHA256 are frozen in the execution manifest. Existing run directories are never reused.

## 6. Smoke gateway

The remaining 14 formal runs are allowed only when the six smoke rows are complete and:

1. no smoke row is `INFRA_FAIL`, `TIMEOUT`, or `INVALID`;
2. no model fallback occurred;
3. every actual model-facing surface exactly matches its arm allowlist;
4. at least 2/3 SMC smoke runs used both Browser perception and Browser action;
5. at least 2/3 legacy smoke runs performed at least one confirmed physical Playwright execution.

If the gate fails, preserve the evidence and stop. Do not tune prompts/runtime and silently resume under the same protocol version.

## 7. Mechanical telemetry and scoring

Primary outcome: predeclared external-state oracle pass/fail.

Per run also record: rounds, total tool calls, privacy-safe tool arg hashes/shape, first mechanical-valid telemetry when available, input/output/cache-hit tokens, wall time, truncation/model/fallback facts, surface hash/size, SMC receipt terminal statuses/no-retry facts, legacy physical-vs-dry-run call counts, and SecurityAgent safety fact for SMC Chrome.

SMC `rejected` is a protocol safety fact, **not automatically a task/model failure**. The task oracle decides task success; protocol/runtime/model/infra facts remain separate fields.

Cache/token and wall-time differences are descriptive secondary metrics because the arms intentionally have different tool-schema prefix bytes. With two repeats, paired deltas are directional evidence only; no statistical-significance claim is allowed.

## 8. Execution manifest / invalidation

Before the first model call freeze and hash:

- exact git HEAD and tracked-clean assertion;
- complete 20-row plan and plan SHA;
- task prompt-template hashes;
- protocol/fixture/worker/runner/analyzer and Browser runtime/tool source hashes;
- model server PID, command hash, model basename and concurrency flags;
- both actual provider-facing lazy tool surfaces and hashes;
- fixed runtime configuration above.

Invalidate a run/matrix rather than reinterpret it if the tracked tree changes, model server identity/config drifts, surface hash changes, a duplicate run directory appears, a foreign 8901 client overlaps a measured start, a model fallback occurs, or an arm exposes a non-allowlisted tool.

## 9. Explicit non-claims

This experiment does not reopen Phase 1 qualification, does not add vision/native UI/root-level scroll, does not claim exhaustive boundary-event detection, and does not change retry/rebind/task-completion policy. It evaluates model use of the existing capability contracts only.
