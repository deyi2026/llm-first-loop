# SMC Browser MF-5.3.4 GroundingRef Treatment Result — 2026-09-16

**Status: COMPLETE_NOT_QUALIFIED.** This document freezes the completed MF-5.3.4 measured treatment. No row was replayed and the frozen Hard Gate was not weakened.

## 1. Frozen identity

- Harness freeze: `03d012b5c6f2dfb0bb1b37cb9bb90bba78c8d1f3`
- Deterministic treatment base: `d644e379a250f9787f51c4d16967828972a4eecd`
- Measured identity: `MF534-ORNITH-v0.1-MEASURED-03d012b5`
- Treatment only: model-visible `object_state` / `object_text` waits use `grounding_ref`; legacy `object_ref` is hidden compatibility only.
- Original six-row prompts, fixture, external oracles, Hard Gate and model/runtime settings remained frozen.

## 2. Final ruling

- External task oracle: **6/6 PASS**; click/fill/delayed-wait each **2/2**.
- `infra_valid=true`, `surface_exact=true`, `model_no_fallback=true`.
- ground-probe amplification: **0**; duplicate successful mutation: **0**.
- Operate failures/errors: **0/0**; automatic retry: **0**.
- Frozen Hard Gate: **FAIL**.
- The Gate failure is independent of the `grounding_ref` treatment: Row 3 has one first-call capability-routing repair (`navigate` sent to `browser_perceive`).

## 3. Row results

| Row | Task | Result | Rounds | Perceive | Operate | First-call valid | Repair | Ground probe |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | click_commit-r1 | PASS | 5 | 2 | 2 | YES | 0 | 0 |
| 2 | fill_submit-r1 | PASS | 9 | 5 | 3 | YES | 0 | 0 |
| 3 | delayed_wait-r1 | PASS | 8 | 5 | 2 | NO | 1 | 0 |
| 4 | delayed_wait-r2 | PASS | 5 | 2 | 2 | YES | 0 | 0 |
| 5 | fill_submit-r2 | PASS | 9 | 5 | 3 | YES | 0 | 0 |
| 6 | click_commit-r2 | PASS | 7 | 4 | 2 | YES | 0 | 0 |

## 4. Treatment result: `grounding_ref` succeeded

- Row 3 later executed an `object_text` wait with provider-visible `grounding_ref`; it succeeded.
- The historically discriminating Row 5 `fill_submit-r2` executed an `object_text` wait with a full `grounding://.../object/el_...` reference and completed with **0 repair / 0 invalid_ref / 0 ground-probe**.
- In frozen MF-5.3.3 Row 5, the corresponding wait used bare `object_ref="el_..."`, was rejected as `object_ref_unavailable:invalid_ref`, and required a model repair.
- Therefore the measured evidence directly supports the narrow treatment claim: replacing ambiguous model-visible `object_ref` with `grounding_ref` removed the prior Row 5 bare-id failure mode.

This does **not** mean the whole Hard Gate passed; the remaining failure is a separate capability-routing issue.

## 5. Independent residual: Perceive / Operate routing

Row 3 `delayed_wait-r1` made its first Browser call as `browser_perceive(action=navigate, url=...)`.

The runtime correctly rejected it because Perceive accepts only `snapshot`, `hydrate`, `diff`, or `wait`. The model then immediately recovered with `browser_operate(do=navigate, ...)`, later used the new `grounding_ref` object wait successfully, and the external oracle passed.

Mechanical Gate consequences:

- first Browser call contract-valid: **5/6** (required 6/6)
- Perceive tool failures: **1**
- protocol-repair episodes: **1**
- all Operate failure/error, ground-probe, duplicate, automatic-retry, fallback and completion/boundary counters remain **0**.

This residual must be audited as a capability-routing / provider-surface problem, not as a GroundingRef regression.

## 6. Aggregate diagnostics

- rounds: **43**
- Perceive calls: **23**
- Operate calls: **14**
- read_evidence calls: **0**
- input tokens: **282396**
- output tokens: **4235**
- cache-hit tokens: **233157**

## 7. Artifact freeze

- `execution-manifest.json` — `c21f245cfab710c8f4e6710ce1b51ed8c200d3233f32df1ef3108e7dce24d820` (56051 bytes)
- `plan.json` — `3be7bac592c6971a9910020a17a76798b4f9b2d50735fc27790f0f5886a6c718` (1261 bytes)
- `results.jsonl` — `d5e30a9cbbe322bbb4c27c697126b6fbf4c81e8faaa09235deb9aff623dedd78` (26955 bytes)
- `qualification-gate.json` — `0f9f090b25309a5ceff414848748aaf7b6a9fc1d84551888f971c196ebfd80a5` (1504 bytes)
- Row 3 raw event log — `b2ff5c34d83fc8b8eb20449f3b25ef2ca8bd36c1ccb52987c275bc9262d221e9` (134503 bytes)

The machine-readable companion freezes all six `worker-result.json` hashes, the exact Row 3 routing failure, both successful MF534 `grounding_ref` object-wait observations, and the prior MF533 Row 5 discriminator.

## 8. Next boundary

The next phase is **read-only routing audit only**:

- inspect provider-visible names, compact descriptions, lazy/full schemas and tool ordering for `browser_perceive` and `browser_operate`;
- compare the exact Row 3 first call with the five contract-valid first calls;
- identify whether any provider-visible overlap or wording makes navigation appear admissible under Perceive;
- do **not** change production, prompts, Gate, task fixtures, retry behavior or model runtime during the audit.

Any proposed correction must be frozen later as a separate deterministic RED before production implementation.
