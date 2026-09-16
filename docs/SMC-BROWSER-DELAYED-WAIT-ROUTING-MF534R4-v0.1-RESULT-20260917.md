# SMC Browser MF534-R4 Targeted delayed_wait Routing Reproduction — 2026-09-17

**Status: COMPLETE_INCONCLUSIVE_CEILING.** The frozen 8-pair / 16-row Ornith diagnostic completed with no row replay. The measurement itself is valid, but the historical A-control routing discriminator did not reproduce, so the compact-description treatment effect is not identifiable from this run.

## 1. Frozen identity

- Measured HEAD: `5fcb032f15c76a16b13c22b52420d5eb4e7c2612`
- Routing RED: `3fe30b5c07a34394b6c46234c554d5d7789ff47e`
- Ref-kind / intent→tool-JSON RED: `ce688c0c3de6e2c48cfb54a729f0d7ba486a284f`
- Production compact-description anchor: `d908adbf58610e1c136ede69b33203acc7422207`
- Measured identity: `MF534R4-ORNITH-TARGETED-v0.1-MEASURED-5fcb032f`
- Plan SHA-256: `1205312ba98e9fe41254e0dc74ef558df0101e0d3456f1ffd9f706eb3ddcc2ee`
- Task: only the original MF534 `delayed_wait` discriminator, 8 paired repeats / 16 rows.
- A = current compact descriptions; B = the already-frozen compact-description-only peer-binding treatment.

## 2. Final ruling

- External task oracle: **A 8/8, B 8/8**.
- First-call routing: **A 8/8, B 8/8**.
- Cross-capability routing failures: **A 0, B 0**.
- Protocol repairs: **A 0, B 0**.
- Mechanical safety: **A=true, B=true**.
- Measurement validity: **true**.
- `control_discriminator_observed=false`.
- Pre-registered targeted signal: **`INCONCLUSIVE_CEILING`**.

This is not evidence that B is ineffective, and it is not evidence that B improves routing. The historical failure (`browser_perceive(action=navigate, ...)` before recovery to `browser_operate(do=navigate, ...)`) simply did not recur in any of the eight A-control repeats. Without an A-control discriminator, the A/B treatment effect is not identifiable in this run.

No full qualification or production change is authorized by this result.

## 3. Per-arm diagnostics

| Arm | Task PASS | First-call routing PASS | Cross-cap failures | Repairs | Rounds | Tool calls | Input tokens | Output tokens | Cache-hit tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 8/8 | 8/8 | 0 | 0 | 49 | 41 | 292542 | 4862 | 216942 |
| B | 8/8 | 8/8 | 0 | 0 | 45 | 37 | 245777 | 4443 | 189662 |

Token/cache/round/tool-count differences are diagnostic only. They do not rescue the absent A-control discriminator and are not treatment-quality conclusions.

## 4. Row results

| Row | Pair | Arm | Task | First-call routing | Rounds | Repair |
|---:|---|:---:|:---:|:---:|---:|---:|
| 1 | delayed_wait-r1 | A | PASS | PASS | 6 | 0 |
| 2 | delayed_wait-r1 | B | PASS | PASS | 5 | 0 |
| 3 | delayed_wait-r2 | B | PASS | PASS | 6 | 0 |
| 4 | delayed_wait-r2 | A | PASS | PASS | 5 | 0 |
| 5 | delayed_wait-r3 | A | PASS | PASS | 7 | 0 |
| 6 | delayed_wait-r3 | B | PASS | PASS | 7 | 0 |
| 7 | delayed_wait-r4 | B | PASS | PASS | 5 | 0 |
| 8 | delayed_wait-r4 | A | PASS | PASS | 7 | 0 |
| 9 | delayed_wait-r5 | A | PASS | PASS | 5 | 0 |
| 10 | delayed_wait-r5 | B | PASS | PASS | 5 | 0 |
| 11 | delayed_wait-r6 | B | PASS | PASS | 6 | 0 |
| 12 | delayed_wait-r6 | A | PASS | PASS | 6 | 0 |
| 13 | delayed_wait-r7 | A | PASS | PASS | 6 | 0 |
| 14 | delayed_wait-r7 | B | PASS | PASS | 5 | 0 |
| 15 | delayed_wait-r8 | B | PASS | PASS | 6 | 0 |
| 16 | delayed_wait-r8 | A | PASS | PASS | 7 | 0 |

All 16 rows began with a contract-valid Browser capability call; no later task success was needed to overwrite or repair a first-call routing failure.

## 5. Surface isolation

- Lazy surface A SHA-256: `6dcc769d109677f069910dc39baac72feb731101bda0652c882c6ddc9a00e1d2`
- Lazy surface B SHA-256: `46da5c3da9d3605256098669f1cdc884f433675e096eb51fed2fe2e84f1ad4fc`
- Full surface equal: **true**
- Perceive parameter schema equal: **true**
- Operate parameter schema equal: **true**
- Deterministic compact-boundary score: A RED / B GREEN.
- The measured variable remained compact-description-only; tool names, `action`/`do`, schemas, task prompt, fixture and runtime mechanics were frozen.

## 6. Relation to the prior incidents

The original MF534 measured run contained one stochastic delayed_wait first-call cross-capability slip. MF534-R2 then produced a different B-row failure in `fill_submit`, which the independent MF534-R3 RED localized to ref-kind / intent→tool-JSON binding rather than Perceive/Operate routing.

MF534-R4 intentionally excluded `fill_submit` and repeated only delayed_wait. It produced 16 clean first calls. Therefore the clean R4 result does not erase the historical MF534 failure; it shows that this particular routing defect was not reproducible in eight fresh A-control trials under the frozen current identity.

## 7. Artifact freeze

- `execution-manifest.json` — `f70b6e82366b1db079a0f31c6e10052ea992aecc8bb9698abb1465bce35b2c74` (65583 bytes)
- `plan.json` — `bb517d5d8d48946394887cbd4a9eb36d8c791604ac5f92460dcb766fe1873ddb` (3530 bytes)
- `results.jsonl` — `f1e396a63f7687ef0b217ead7dcb07d29a0ca275a754cbb9e8b3b7260c1e2e16` (77009 bytes)
- `diagnostic-gate.json` — `af5fdf4e7ffeee4a78d7e0ad3dc1651aa09525bafbe6baf0e70694eebefc65c5` (2380 bytes)

The machine-readable companion also freezes SHA-256 and byte size for all 16 `worker-result.json` files plus per-row first-call summaries. Raw Chrome profiles and full run directories remain untracked evidence and are not committed.

## 8. Next boundary

- Do **not** modify production from this result.
- Do **not** launch a full compact-description A/B solely from this ceilinged diagnostic.
- Keep tool-name-only, `action/do`-only, ref-kind binding, and Config Authority P1-C as separate work lines.
- If routing is revisited, first decide whether additional reproduction is worth the model budget or whether the historical failure should remain a low-frequency observed residual with frozen regression evidence.
