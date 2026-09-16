# SMC Browser MF-5.3.2 Cognition-Preserving Treatment Result — 2026-09-16

Status: **COMPLETE / NOT QUALIFIED**

- Protocol commit: `5dffb6b37d928f34ab558789e768c5336a1cb7c4`
- A capability-identity implementation: `dfca4c959279c639c8b9b6febe9ba79325af33b6`
- B evidence-quality projection implementation: `05d0f36c7202a8c183a517813815f6ef83f2cfe4`
- Valid measured identity: `MF532-ORNITH-v0.1-MEASURED2-5dffb6b3`
- Machine-readable result SHA-256: `72b9c897c2b74ac428e8b245aa08d00d2ac21bced2bf8fbd6aa82ffd59161390`

## 1. Final ruling

The frozen hard Gate is **false**. This treatment must not be promoted as qualified.

At the same time, task correctness and qualification must be kept separate:

- external fixture oracle: **6/6 PASS**;
- click_commit: **2/2**;
- delayed_wait: **2/2**;
- fill_submit: **2/2**;
- one row (`fill_submit-r1`) hit the frozen **240s worker TIMEOUT after its save action had already succeeded**;
- four completed workers still emitted one Perceive contract failure each;
- ground-probe amplification: **0**;
- Operate failures/errors: **0/0**;
- duplicate successful mutations: **0**;
- hidden atomic Browser calls / auto mutation retry / task-completion authority / undeclared-boundary continuation: **0**.

Therefore the result is **task-correct but not protocol/infra-qualified**.

## 2. Frozen Gate

| Gate | Result |
|---|---:|
| Complete rows | 6/6 |
| Infra valid | **false** |
| External oracle | **6/6** |
| Per-task oracle | **2/2 each** |
| First Browser contract-valid (frozen worker metric) | **1/6** |
| First Browser contract-valid (raw reconstruction including TIMEOUT row) | **2/6** |
| Perceive failures / errors | **4 / 0** |
| Protocol repair episodes | **4** |
| Operate failures / errors | **0 / 0** |
| `get_tool_schema` | 0 |
| Ground-probe amplification | **0** |
| Duplicate successful mutation | 0 |
| Model fallback / SecurityAgent | 0 / false |
| Auto mutation retry | 0 |
| Task-completion authority violations | 0 |
| Undeclared boundary continuations | 0 |

The frozen Gate reports first-call validity as 1/6 because the TIMEOUT row has no final worker-result metrics. Its raw event log shows the first Browser call was the correct `browser_operate(do=navigate)`, so the mechanical raw reconstruction is 2/6. The Gate itself is not rewritten.

## 3. Row results

| Row | Task | Status | Oracle | Rounds | Repair | Ground probe |
|---:|---|---|---|---:|---:|---:|
| 1 | click_commit r1 | PASS | PASS | 11 | 1 | 0 |
| 2 | fill_submit r1 | **TIMEOUT** | **PASS** | n/a | n/a | n/a |
| 3 | delayed_wait r1 | PASS | PASS | 6 | 0 | 0 |
| 4 | delayed_wait r2 | PASS | PASS | 6 | 1 | 0 |
| 5 | fill_submit r2 | PASS | PASS | 12 | 1 | 0 |
| 6 | click_commit r2 | PASS | PASS | 12 | 1 | 0 |

## 4. MF-5.3.2A — capability identity result

Changing the provider-visible hand from `browser_semantic_operation` to the peer name `browser_operate` was deterministic-safe but **not sufficient to eliminate first-call routing misuse**.

The four observable failures were still first-call Perceive misuse:

- Row 1: `browser_perceive(action=snapshot, url=...)` -> snapshot rejects `url`;
- Row 4: `browser_perceive(action=navigate, url=...)` -> unsupported action;
- Row 5: same unsupported `navigate` misuse;
- Row 6: `browser_perceive(action=snapshot, url=...)` -> snapshot rejects `url`.

Row 3 correctly started with `browser_operate(do=navigate)`. The TIMEOUT Row 2 raw event log also started correctly with `browser_operate(do=navigate)`.

**Adjudication:** the peer-name correction is clean architecture, but the live evidence does not support treating it as a sufficient routing fix. Do not add navigation authority to Perceive and do not replace this with a routing thought protocol.

## 5. MF-5.3.2B — evidence-quality projection result

The B deterministic contract remains intact: only the bounded model projection is reordered by `complete coverage -> stable/non-snapshot-local identity -> opaque id`; canonical persisted objects, `objects_ref`, hydration, diff and grounding semantics remain unchanged.

The live treatment is consistent with the intended effect:

- ground-probe amplification changed from MF-5.3.1 **1 -> 0**;
- both fill tasks had external oracle PASS;
- Row 5 selected `{kind:button,name:"Save code"}`, exact-match count=1, and completed the click without ambiguity.

Because A and B were combined in the same live treatment, this is **supportive evidence, not single-variable causal proof**. The deterministic B tests remain the isolated evidence for the projection change itself.

## 6. Row 2 TIMEOUT is post-success amplification

Row 2's fixture oracle reports `save_count=1` and `value_match=true`: the required action happened exactly once.

The raw tool-event sequence before timeout was mechanically:

1. Operate navigate;
2. Perceive snapshot;
3. Operate set_text;
4. Operate click Save code;
5. Perceive snapshot;
6. read evidence;
7–10. four exact hydrates;
11. another snapshot with `projection_limit=500`;
12. another evidence read;
13. worker hits the frozen 240s timeout before returning a terminal run result.

This is not evidence that the iteration limit should be raised. It is evidence that **post-success verification/evidence amplification can consume the run after the external task action is already complete**. Completion meaning remains model-owned; the next correction should improve evidence sufficiency / verification economy rather than let the program decide task success.

## 7. Comparison to MF-5.3.1

| Metric | MF-5.3.1 | MF-5.3.2 |
|---|---:|---:|
| Infra valid | true | **false (1 timeout)** |
| Task oracle | 5/6 | **6/6** |
| Fill oracle | 1/2 | **2/2** |
| Ground-probe amplification | 1 | **0** |
| Protocol repairs | 3 | 4* |
| Perceive failures | 3 | 4* |
| Operate failures | 0 | 0 |
| Frozen first-call valid | 3/6 | 1/6* |

`*` MF-5.3.2 worker aggregates omit the TIMEOUT row. Raw reconstruction makes first-call validity 2/6, not 1/6. Aggregate rounds/tokens/cache/read counts are therefore **not apples-to-apples efficiency totals** and are not used to claim an efficiency win.

## 8. Orchestration-invalid first attempt

An earlier root `MF532-ORNITH-v0.1-MEASURED-5dffb6b3` was intentionally frozen as **infra-invalid**. A single command was asked to contain all six rows, but the host command envelope is 600s while each frozen worker may consume up to 240s. After Rows 1–3 completed, Row 4 had begun; continuing would inevitably allow the host to kill a later formal row.

The attempt was terminated and preserved. No row was deleted, copied into the valid identity, or selectively replayed under that identity. The valid treatment restarted all six rows in a fresh identity using one frozen row per runner invocation. Model, prompt, fixture, schema, Gate and manifest identity were unchanged.

## 9. Deterministic qualification before live treatment

- A RED: `7723a2715cc334d46cdfb9c819b9bb3c40af8a1d`;
- A implementation: `dfca4c959279c639c8b9b6febe9ba79325af33b6`;
- B RED: `5da9d8a86350f0d9225e0e1a6cae2d99ffa84d85`;
- B implementation: `05d0f36c7202a8c183a517813815f6ef83f2cfe4`;
- Browser/Factory broad regression: **363/363 PASS**;
- full `tests -m not real_llm`: **100%, exit 0, 0 FAILED / 0 ERROR**;
- Ruff: PASS;
- Pyright: **0 errors / 0 warnings**;
- security/diff checks: PASS.

## 10. Artifact freeze

### Valid six-row identity

- `execution-manifest.json` — 55991 bytes — SHA-256 `6ed64cd8f4f058aebbea114d7937ba82996ac897a078b4ec6eefa11c7949088e`
- `plan.json` — 1315 bytes — SHA-256 `c8d925d0ea7dd3986a30bd4cc9f0d8eac2692f3f7578b903e6e269955e371a78`
- `qualification-gate.json` — 1505 bytes — SHA-256 `c33b2e2aeb1b5310cbf8f87466e59d710593b6ad80636cf72e044e74120ff4dc`
- `results.jsonl` — 26207 bytes — SHA-256 `9ae23ccc39a22c8a845f6910955360d2417e43c80afca0d6af3c4e97a94e01d3`

### Infra-invalid orchestration attempt

- `execution-manifest.json` — 55991 bytes — SHA-256 `6ed64cd8f4f058aebbea114d7937ba82996ac897a078b4ec6eefa11c7949088e`
- `plan.json` — 1315 bytes — SHA-256 `c8d925d0ea7dd3986a30bd4cc9f0d8eac2692f3f7578b903e6e269955e371a78`
- `results.jsonl` — 16833 bytes — SHA-256 `4d46258aede25beac9f20bc47a742567557f43b2c7d5768e17632a8023709317`
- `attempt-invalid.json` — 821 bytes — SHA-256 `29fd986dde5d00ced9875a51f3b45976737876705418ec6dfd69c0d204fbffe0`


## 11. Final disposition

**MF-5.3.2 v0.1 is NOT QUALIFIED.**

Do not rerun or reinterpret this identity to obtain a pass. Do not loosen the Gate. Do not raise `max_iterations` as the remedy. Do not proceed to MF-6.

The evidence now separates the remaining work more sharply:

1. capability routing remains unstable even after peer naming;
2. ambiguous-grounding amplification improved to zero and both fill tasks became task-correct;
3. post-success verification/evidence amplification can still prevent timely run closure.

Any next correction should start with a fresh deterministic/read-only design step and a new qualification identity.
