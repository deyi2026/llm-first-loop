# SMC Browser MF-5.3.3 Cognition-Preserving Treatment Result — 2026-09-16

**Status: COMPLETE_NOT_QUALIFIED.** This document freezes the completed MF-5.3.3 B1+A' measured treatment. No row is replayed and no Gate is weakened.

## 1. Frozen identity

- Harness freeze: `fc01ddc1eb4b7a075318ea86b71652fbf12cb46a`
- Deterministic treatment base: `14dfdb407a098d4efa3c9c16476dd0a5239ceb39`
- Measured identity: `MF533-ORNITH-v0.1-MEASURED-fc01ddc1`
- Treatment only: B1 direct DOM text preservation + A' URL-role disambiguation.
- Original six-row prompts, fixture, external oracles, Hard Gate, model/runtime settings remained frozen by the MF533 protocol.

## 2. Final ruling

- External task oracle: **6/6 PASS**; click/fill/delayed-wait each **2/2**.
- `infra_valid=true`, `surface_exact=true`, `model_no_fallback=true`.
- first Browser call contract-valid: **6/6**.
- ground-probe amplification: **0**; duplicate successful mutation: **0**.
- Operate failures/errors: **0/0**.
- Frozen Hard Gate: **FAIL**, solely because Row 5 produced **1 Perceive failure / 1 protocol-repair episode**.

## 3. Row results

| Row | Task | Result | Rounds | Perceive | Operate | Repair | Ground probe |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | click_commit-r1 | PASS | 6 | 3 | 2 | 0 | 0 |
| 2 | fill_submit-r1 | PASS | 11 | 5 | 3 | 0 | 0 |
| 3 | delayed_wait-r1 | PASS | 6 | 3 | 2 | 0 | 0 |
| 4 | delayed_wait-r2 | PASS | 7 | 4 | 2 | 0 | 0 |
| 5 | fill_submit-r2 | PASS | 12 | 8 | 3 | 1 | 0 |
| 6 | click_commit-r2 | PASS | 5 | 2 | 2 | 0 | 0 |

## 4. The sole residual failure

Row 5 `fill_submit-r2` successfully set the Project code, then attempted an `object_text` wait using the snapshot's bare semantic id (`el_...`) as provider-visible `object_ref`.

The runtime correctly rejected it with:

`object_ref_unavailable:invalid_ref; no polling started`

The model then recovered without automatic runtime rebind/retry: it took a new snapshot, used the full `grounding://.../object/el_...` reference for exact hydration, verified the value, clicked Save code, and the external oracle passed.

This is not the prior URL-routing defect. It is a narrower provider-contract naming ambiguity: snapshots expose both a bare `id` and a full `grounding_ref`, while object waits call the required field `object_ref`.

## 5. Treatment signals

### A' URL-role disambiguation

- MF-5.3.2 frozen first-call contract-valid: **1/6**; raw-event reconstruction: **2/6**.
- MF-5.3.3: **6/6**.
- B1 cannot influence the first Browser call before any page perception result exists, so the measured first-call improvement is specifically consistent with A'.

### B1 direct DOM text preservation

- Prior MF-5.3.2 Row 2 complete DOM+AX `Submission status` objects exposed no direct text.
- MF-5.3.3 exposes direct `Not submitted` / `Submitted` text on the stable object, and Row 2 completed normally rather than ending as an oracle-true worker timeout.
- This is a mechanical representation improvement; one treatment run is not sufficient to claim B1 alone caused the timeout disappearance.

## 6. Aggregate diagnostics

- rounds: **47**
- Perceive calls: **25**
- Operate calls: **14**
- read_evidence calls: **3**
- input tokens: **364917**
- output tokens: **5275**
- cache-hit tokens: **308079**

## 7. Artifact freeze

- `execution-manifest.json` — `bce6c5a13789fdf3f94e26919e9d487fbec61228ebbaf5e22e9defb789d5d856` (56027 bytes)
- `plan.json` — `e1a53f539e8781377056575b687026100a18df61f3f1d9ea5899c9c0345f4802` (1321 bytes)
- `results.jsonl` — `94c7efa27e4efc529de0c3f877c3243c5bc301499a6a9b43d06085a6d62a2184` (28169 bytes)
- `qualification-gate.json` — `92d5cdab60a633a30eb1655a786aec03ffbb2d936bc39f6f22386520f65c1fb7` (1505 bytes)

- Row 5 raw event log — `61ede2c1321855b48dbaa20267f47a7df6ae567cfc7de8b2e93e7ac60ea35b00` (229536 bytes)

The machine-readable companion `docs/SMC-BROWSER-COGNITION-PRESERVING-MF5.3.3-v0.1-RESULT-20260916.json` additionally freezes every row `worker-result.json` hash and the exact residual failure classification.

## 8. Next boundary

This result does **not** authorize a production correction. The next deterministic step is an isolated RED contract only:

- model-visible `object_state` / `object_text` waits use **`grounding_ref`**;
- provider-visible `object_ref` disappears;
- historical/internal `object_ref` remains executable only as hidden compatibility;
- exact-ref validation remains fail-closed; no fuzzy/latest/rebind/automatic retry is introduced.

No new live-model qualification should run until that deterministic correction is separately implemented and qualified.
