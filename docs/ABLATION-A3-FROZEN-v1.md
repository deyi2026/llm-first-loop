# A3 Action-Plane Loop Guard — FROZEN v1

> Status: **FROZEN — READY FOR REAL A3 EXECUTION**
> Scope: MiniMax-M3 + deepseek-v4-flash anchors only; not production/cross-vendor promotion.
> Treatments: byte-identical Full-Slim-v1 prompt; only Action-Plane mechanics differ.
> Measurement: frozen v2.1.
> User authorization: current turn approved executing the recommended A3 sequence.

## 1. Frozen Design

- New I01-I08 fixture family; A2 G01-G08 are development evidence only and excluded from A3 performance statistics.
- 4 treatments: NoGuard, DuplicateSuppression, BudgetTerminal, CombinedGuard.
- 2 providers × 8 seeds × 4 treatments = 64 real generations.
- randomization seed `202608261500`; 32 independently randomized runs/provider.
- 8 preselected secondary reviews: one/provider/treatment before outputs.
- I03/I04/I07 require two independent current sources and form explicit under-verification controls.
- Measurement v2.1: cross-provider primary judge for every run; preselected/mandatory secondary; disagreement => ABSTAIN.

## 2. Frozen Mechanism Gate

Exactly `docs/ABLATION-A3-PRE-REGISTRATION-v1.md` and executable `scripts/calib/analyze_a3.py` apply. Per-provider hard gates prevent cross-anchor averaging from masking a regression. A survivor additionally requires material cross-anchor reduction in attempts, rounds, or prompt tokens. Winner selection is also frozen in `analyze_a3.py`.

## 3. Execution Governance

From A3-001 onward:
- `runner.py`, A2 artifacts, action guard, A3 runner/fixtures/matrix/provider profile, Measurement v2.1, judge prompt/protocol, and analysis gates are immutable;
- raw artifacts are never overwritten; existing real artifacts are skipped;
- no automatic generation retry and no fallback provider/model;
- provider blocks may be split into bounded batches without changing frozen order;
- valid judge cache files are never overwritten;
- one invalid/non-parseable judge response that creates no artifact may receive one exact missing-judgment continuation; a repeated format failure stops judging;
- a genuine Measurement semantic bug stops interpretation.

## 4. Pre-Execution Validation

- A3 targeted mechanism/fixture tests: **16/16 PASS**.
- full calibration/measurement/screening/A1/A2/A3 regression set: **193/193 PASS**.
- final dry matrix: **64/64 COMPLETED**, 0 ROUND_LIMIT, 0 INFRA_FAILURE; attempts/executions 1..2; 40 one-execution cases and 24 two-execution cases.
- `data/calib/runs_a3` empty after dry cleanup.
- `data/calib/a3_judges` empty.
- MiniMax/DeepSeek credentials detected; secret values not stored.

## 5. Frozen SHA-256

| Artifact | SHA-256 |
|---|---|
| `docs/MEASUREMENT-FROZEN-v2.1.md` | `f6b12b650ffd93afc73eb2732c9b3969020b05b98678b229e1c6c908bfc83ce3` |
| `docs/ABLATION-A2-RESULT-v1.md` | `cfee69b5a754876f28d812c144f4b74f5479473b0383c1abb5f9584dc6033243` |
| `scripts/calib/semantic_judge_v21.py` | `a52ade5b9cc9bed5797e66995ee00b4de71b98568af5d806f5af661bfd868ffd` |
| `scripts/calib/runner.py` | `dacac2dc295904fd24a2eb6dfe08a8a98b5cb6298a987dd21bbe9c61064f30e6` |
| `scripts/calib/treatments.py` | `700fb678a046b5cad210d55d1d0d873d69aa6c3f7f179d49e57fa2e00cd5c9c2` |
| `scripts/calib/treatments_a1.py` | `2c17a75434065633a642af7aabf0361ced1f4ee3a76d7f3b57c666238dca9f62` |
| `scripts/calib/treatments_a2.py` | `d15f08201dc79097ff3267483fcceee83916992246d07ccc9cdb3a8d2a287176` |
| `scripts/calib/action_guard.py` | `2e17f45a6276676649ec184045a69f58a0aa857c2d7614f04ec976801d123ec4` |
| `scripts/calib/runner_a3.py` | `ab304d2d6cb3f2b83b3ba9a5ab6acf29843056afdf18cfdcef712e36df00c1d8` |
| `scripts/calib/fixtures_a3.py` | `873097ed20441db57f6b6524fc9c61fb607e48d6e9c19da2b941a9b0c11c4fe6` |
| `scripts/calib/run_a3.py` | `3a658abf22debe227f90c70a64017ccd1b1a98dbe267823e112ac68ef13421c4` |
| `scripts/calib/judge_a3.py` | `413fb901823304ed0522f2845e167ed9d36ce01b73611ded654fb0f5f9ae4efd` |
| `scripts/calib/analyze_a3.py` | `d37640dc62cd26c56c934aad034fb08e17c0bb7af62349142886e85ff7a828d1` |
| `data/calib/a3_matrix_v1.json` | `3bbbaebfc2f60f9746e6596bb288e23bd4ce7a78222663c89113137108205568` |
| `data/calib/a3_provider_manifest.json` | `c31174cc83ad07949bc99ed8267f45ff50cb5ab545232d48504c498cf104f053` |
| `data/calib/a3_dry_report_v1.json` | `857b325a4b4ec87b754e717eb921ed85c17ca2c6c85b08dfb72b382cc84a71d5` |
| `docs/ABLATION-A3-DEVELOPMENT-v1.md` | `d690481f55581f2a5c645e6752a9e10a72559935f764d135b4c56a80cb681044` |
| `docs/ABLATION-A3-PRE-REGISTRATION-v1.md` | `527e03805f3109cb8be629fd19acb5a34fa44dcd0729c802fe4e0c56400d4a26` |
| `docs/ABLATION-A3-MATRIX-v1.md` | `929d27cb9924dcdc9d4da16e2b908a3d244800c7b1f4a6a5d5f4341722676b98` |
| `tests/unit/test_action_guard_a3.py` | `324e1fd9eba243bbc87c9de994b0c5328d58fdcad70e343d7450a691f36a5318` |
| `tests/unit/test_calib_a3.py` | `d5689f06a4042f5f139bc8f0e8504a11850ecae1fde7efa5ddb1e1c066f5f225` |

The freeze document itself is hashed separately and is not self-listed.
