# A2 Full-Slim Confirmation — FROZEN v1

> Status: **FROZEN — READY FOR REAL A2 EXECUTION**
> Scope: MiniMax-M3 + deepseek-v4-flash anchors only; not cross-vendor/global promotion.
> Candidate: **Full-Slim-v1 = Contract + DRU / Stop-Investigating only** (mechanically fixed by A1).
> Measurement: frozen v2.1.
> User authorization: current turn approved executing the recommended A1→A2 sequence.

## 1. Frozen Design

- 8 entirely new fixtures G01-G08; no A1/S2/calibration fixture reuse.
- 4 treatments: Baseline, Contract, Full-Slim-v1, Current Full reference.
- 2 providers × 8 seeds × 4 treatments = 64 real generations.
- 32 runs/provider in independently randomized provider blocks.
- randomization seed `202608261030`.
- 8 secondary reviews preselected before outputs: exactly one/provider/treatment.
- every run gets cross-provider primary v2.1 judge; mandatory secondary for non-COMPLETED/task failure/fatal/non-N4.
- valid primary/secondary disagreement => whole run ABSTAIN; valid judge caches never rewritten.

## 2. Frozen Candidate Gate

Exactly the thresholds in `ABLATION-A2-PRE-REGISTRATION-v1.md` and executable `analyze_a2.py` apply.

A2 `PASS-CANDIDATE` requires all of the following:
- semantic pair sufficiency >=6/8 vs Baseline/Contract/Current Full on both anchors;
- no forbidden fatal/constraint regression;
- no paired Task or N4 drop >=2 vs Baseline or Current Full;
- no additional Full-Slim ROUND_LIMIT vs Baseline;
- Full-Slim requests and unnecessary verification non-worse than Baseline on **both** anchors;
- cross-anchor aggregate improvement >=2 in requests or unnecessary verification;
- Full-Slim aggregate prompt tokens <=0.80× Current Full on **each** anchor;
- Full-Slim mean latency <=1.10× Current Full on **each** anchor;
- no material (>+2/+2) tool-efficiency regression vs Current Full on either anchor.

Any frozen-gate violation => `FAIL`. There is no near-pass override.

## 3. Execution Governance

From A2-001 onward:
- treatments, G01-G08, matrix, provider profiles, Measurement v2.1, judge prompt/protocol, and candidate gates are immutable;
- raw artifacts are never overwritten; existing real artifacts are skipped;
- no automatic generation retry and no fallback provider/model;
- provider blocks may be split into bounded batches without changing frozen order;
- valid judge cache files are never overwritten;
- an invalid/non-parseable judge response that creates no valid artifact is an infra-format event, not a judgment; at most one exact missing-judgment continuation is permitted, disclosed in result integrity; a repeated format failure stops A2 judging;
- a genuine new Measurement semantic bug stops A2 interpretation.

## 4. Pre-Execution Validation

- A2 targeted tests: 10/10 PASS.
- final dry matrix: 64/64 COMPLETED, 0 ROUND_LIMIT, 0 INFRA_FAILURE, requests range 1..2.
- full calibration/measurement/screening/A1/A2 regression set: 173/173 PASS.
- `data/calib/runs_a2` empty after dry cleanup.
- `data/calib/a2_judges` empty.
- provider manifest: MiniMax/DeepSeek credentials detected; secret values not stored.

## 5. Frozen SHA-256

| Artifact | SHA-256 |
|---|---|
| `docs/MEASUREMENT-FROZEN-v2.1.md` | `f6b12b650ffd93afc73eb2732c9b3969020b05b98678b229e1c6c908bfc83ce3` |
| `docs/ABLATION-A1-FROZEN-v1.md` | `858251c629974057b0a3d4e261a07f597f78dfcd37cd234091e94b393310b562` |
| `docs/ABLATION-A1-RESULT-v1.md` | `455136cbca91fdd55bba7fe2e12648060782261be14bff077f371b40fd270e52` |
| `data/calib/a1_analysis.json` | `4058d3fadd7794cec7b59edc1eb23871a8911aa2dc3dc93cef4adb83e71371ea` |
| `scripts/calib/semantic_judge_v21.py` | `a52ade5b9cc9bed5797e66995ee00b4de71b98568af5d806f5af661bfd868ffd` |
| `scripts/calib/treatments.py` | `700fb678a046b5cad210d55d1d0d873d69aa6c3f7f179d49e57fa2e00cd5c9c2` |
| `scripts/calib/runner.py` | `dacac2dc295904fd24a2eb6dfe08a8a98b5cb6298a987dd21bbe9c61064f30e6` |
| `scripts/calib/treatments_a1.py` | `2c17a75434065633a642af7aabf0361ced1f4ee3a76d7f3b57c666238dca9f62` |
| `scripts/calib/treatments_a2.py` | `d15f08201dc79097ff3267483fcceee83916992246d07ccc9cdb3a8d2a287176` |
| `scripts/calib/fixtures_a2.py` | `41ff0487c78f4d92a3c4bbab3098f98e47b73f4341d9c27ed374a2de52d795dc` |
| `scripts/calib/runner_a2.py` | `8e3f016a5c2211767bc2ff974bf2ae531a7add345003d0798d535d77c59e88a9` |
| `scripts/calib/run_a2.py` | `3d440664182ed587427442f6dddd6d220bb6915a3f8f84a99f3afec9705f6ff1` |
| `scripts/calib/judge_a2.py` | `ca1bcfa06dcf8f30f7010650ceaf135218235374b666bfd639160cc344e08d90` |
| `scripts/calib/analyze_a2.py` | `59132ced63a7f2aaa47fed258b74073d91b02718d25d5b365231388bba5c6004` |
| `data/calib/a2_matrix_v1.json` | `5b2a0a0aa916d9f71f0b65c703f6fd9625e3f70226e03c5fb7c87c1214eb94f4` |
| `data/calib/a2_provider_manifest.json` | `ba3fc72e026b69c250141140f3eb3456f6cc16544adde3ae041ba4b4e7cd64ef` |
| `docs/ABLATION-A2-PRE-REGISTRATION-v1.md` | `f1a8f8920540a0bbdb30de2f687a06d82ad299ad6ad0802342bb025d33b80832` |
| `docs/ABLATION-A2-MATRIX-v1.md` | `8e97ceacd91dbbce9d35a21686fff8cfcf08183d6a072520e336d5473770ec49` |
| `tests/unit/test_calib_a2.py` | `5ff6b2c0c5570fb0461253b833093282b8232381b621cf2f18912c1f2c85988f` |

The freeze document itself is hashed separately and is not self-listed.
