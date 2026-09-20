# SMC Browser MF534-R2 Compact-Description Routing A/B Result — 2026-09-17

**Status: COMPLETE_INVALID.** The frozen 12-row paired Ornith A/B completed without row replay. The preregistered measurement is invalid because arm B failed one external task oracle; no production treatment conclusion is authorized.

## 1. Frozen identity

- Measured HEAD: `489dd5a47a7636ec0a6791dc1964c35c68bb7cf8`
- Routing RED anchor: `3fe30b5c07a34394b6c46234c554d5d7789ff47e`
- Production compact-description anchor: `d908adbf58610e1c136ede69b33203acc7422207`
- A: exact current compact descriptions.
- B: test-local compact-description-only peer-binding sentences; tool names, parameter schemas, full provider surface, runtime, prompts, fixture and Browser mechanics unchanged.
- Single existing Ornith server on 8901, prompt/decode concurrency 1/1; no second local model and no fallback.

## 2. Final ruling

- First-call routing: **A 6/6, B 6/6**.
- Cross-capability routing failures: **A 0, B 0**.
- External task oracle: **A 6/6, B 5/6**.
- Mechanical safety: **A=true, B=true**; operation failures are 0/0.
- Preregistered result: **measurement_valid=false**, `treatment_signal=INVALID`.
- Therefore this run does **not** support a production compact-description change.
- It also does **not** prove the treatment has no routing effect: the A control itself was 6/6 first-call routing, so the prior stochastic Row3 routing defect did not reproduce and there was no routing discriminator in this sample.

## 3. Row results

| Row | Pair | Arm | Task | First-call routing | Rounds | Repair | Result |
|---:|---|:---:|:---:|:---:|---:|---:|---|
| 1 | click_commit-r1 | A | PASS | PASS | 5 | 0 | PASS |
| 2 | click_commit-r1 | B | PASS | PASS | 5 | 0 | PASS |
| 3 | fill_submit-r1 | B | FAIL | PASS | 12 | 5 | TASK_FAIL |
| 4 | fill_submit-r1 | A | PASS | PASS | 11 | 0 | PASS |
| 5 | delayed_wait-r1 | A | PASS | PASS | 7 | 0 | PASS |
| 6 | delayed_wait-r1 | B | PASS | PASS | 6 | 0 | PASS |
| 7 | delayed_wait-r2 | B | PASS | PASS | 6 | 0 | PASS |
| 8 | delayed_wait-r2 | A | PASS | PASS | 5 | 0 | PASS |
| 9 | fill_submit-r2 | A | PASS | PASS | 11 | 0 | PASS |
| 10 | fill_submit-r2 | B | PASS | PASS | 8 | 0 | PASS |
| 11 | click_commit-r2 | B | PASS | PASS | 6 | 0 | PASS |
| 12 | click_commit-r2 | A | PASS | PASS | 5 | 0 | PASS |

## 4. Why the measurement is invalid

- B row 3 (`fill_submit-r1`) had a valid first Browser call: `browser_operate(do=navigate, ...)`.
- It then successfully snapshotted/hydrated the page and executed `browser_operate(do=set_text, ...)` with `AB-7319`.
- After that, Perceive argument synthesis degraded: one wait added an undeclared `action2`; one `hydrate` carried wait-only fields; three object-text waits were rejected with `object_ref_projection_mismatch`.
- The final snapshot/hydrate confirmed the input contained `AB-7319`, but the model never issued the `Save code` click. External oracle: `save_count=0`, `value_match=false`.
- This is a **within-Perceive branch/argument/reference synthesis slip after successful routing**, not the Perceive/Operate cross-capability routing defect this experiment was designed to discriminate.
- A single stochastic B-row failure cannot establish that the description treatment caused this new slip. It nevertheless invalidates this frozen A/B because both arms were required to preserve 6/6 task correctness.

## 5. Aggregate diagnostics

| Metric | A | B |
|---|---:|---:|
| task oracle PASS | 6 | 5 |
| first-call routing PASS | 6 | 6 |
| cross-capability failures | 0 | 0 |
| protocol repairs | 0 | 5 |
| rounds | 44 | 43 |
| tool calls | 38 | 38 |
| input tokens | 341362 | 279301 |
| output tokens | 5527 | 4748 |
| cache-hit tokens | 272233 | 223997 |

Token/cache/round differences are diagnostics only and do not rescue an invalid correctness gate.

## 6. Surface isolation

- Lazy surface A SHA-256: `6dcc769d109677f069910dc39baac72feb731101bda0652c882c6ddc9a00e1d2`
- Lazy surface B SHA-256: `46da5c3da9d3605256098669f1cdc884f433675e096eb51fed2fe2e84f1ad4fc`
- Full surface equal: **true**
- Perceive parameter schema equal: **true**
- Operate parameter schema equal: **true**
- The measured variable remained compact-description-only.

## 7. Artifact freeze

- `execution-manifest.json` — `8de34e97a6482b40ba74ca576064916e1bbfcd7e9ac5e0a073e12bd55f0b1c73` (65504 bytes)
- `plan.json` — `12c8181bc7a74939dfdf7d383f7e1af8c4bf9bcedb1b4d3d0b930dd03c980eb0` (2638 bytes)
- `results.jsonl` — `c3968d8fda5d0263a212dd7266467ed76ec1e9019de3c1b0238df27fb8c786a0` (61923 bytes)
- `qualification-gate.json` — `9ea501dc769cfd658c8a87607de4e99468e75ea2102182fa0ef20b4a43e6da31` (2027 bytes)
- `row3_raw_event_log` — `43d97fd597a77f260f5d19f78d1f30db9a51c3e41e9ad5da56d952c753cdfe46` (206218 bytes)

The machine-readable companion also freezes all 12 `worker-result.json` hashes and per-row routing/task diagnostics. Raw Chrome profiles and full run directories remain untracked evidence and are not committed.

## 8. Next boundary

- Do **not** modify production from this result.
- Do **not** replay any row under this protocol identity.
- If the compact-description routing hypothesis is measured again, create a fresh independent protocol identity with the same single-variable treatment.
- Separately audit the B row3 Perceive branch/reference synthesis failure; do not relabel it as routing and do not fold a fix into the routing treatment.
- Tool-name-only, `action/do`-only, and Config Authority P1-C remain separate work lines.
