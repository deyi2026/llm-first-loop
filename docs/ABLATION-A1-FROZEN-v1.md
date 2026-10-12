# A1 Anchor Component Ablation — FROZEN v1

> Status: **FROZEN — READY FOR REAL A1 EXECUTION**
> Scope: MiniMax-M3 + deepseek-v4-flash anchors only; not cross-vendor/global promotion.
> User authorization: current turn approved executing the recommended A1 sequence after pre-registration freeze.

## 1. Frozen Question

Which individual Architecture components produce useful marginal behavior over the compact Contract, and which only add cost or provider-specific interaction?

The only component-survival candidates are A2-A5. Baseline, Contract, and Current Full are references.

## 2. Frozen Matrix / Review

- 8 new paired seeds F01-F08.
- 7 treatments.
- 2 anchor providers.
- 112 real generations: 56 MiniMax, then 56 DeepSeek; each provider block is independently randomized by the frozen matrix.
- randomization seed `202608261001`.
- 14 secondary reviews preselected before results: exactly one/provider/treatment.
- primary semantic judge is cross-provider for every run; mandatory secondary review for non-COMPLETED, task failure, fatal, or non-N4.
- disagreement => whole run ABSTAIN; no re-judge inside A1.

## 3. Measurement / Classification

Measurement is frozen v2.1. No regex/free-form semantic scorer may be reintroduced.

Component classification and Full-Slim eligibility are exactly those in `ABLATION-A1-PRE-REGISTRATION-v1.md` and executable `analyze_a1.py`.

Semantic pair sufficiency: <6/8 valid paired seeds on either provider => hard screen-out for measurement insufficiency.

A future Full-Slim candidate may include **only** A1 components classified `keep` by the frozen analysis.

## 4. Execution Governance

From the first A1 real generation onward:

- treatment prompts, F01-F08, matrix, provider profiles, Measurement v2.1, judge protocol, and classification rules receive zero edits;
- raw artifacts are never overwritten; the runner skips an existing real run artifact;
- no automatic retry. INFRA_FAILURE remains recorded and becomes missing/invalid paired data under the frozen sufficiency rule;
- no fallback provider/model;
- provider blocks are executed in frozen block sequence, optionally split into bounded batches without changing order;
- scoring occurs after generation; judge cache files are never rewritten;
- any genuine new Measurement v2.1 semantic bug stops A1 effectiveness interpretation and returns to measurement versioning/holdout discipline.

## 5. Pre-Execution Validation

- final A1 dry matrix: 112/112 COMPLETED; 0 INFRA_FAILURE; 0 ROUND_LIMIT; requested_count range 1..2.
- targeted A1 tests: 9/9 PASS.
- calibration + measurement + screening + A1 regression set: 163/163 PASS.
- `data/calib/runs_a1`: empty after dry cleanup.
- `data/calib/a1_judges`: empty.
- provider manifest: MiniMax and DeepSeek credentials detected; key values are not stored.

## 6. Frozen SHA-256

| Artifact | SHA-256 |
|---|---|
| `docs/MEASUREMENT-FROZEN-v2.1.md` | `f6b12b650ffd93afc73eb2732c9b3969020b05b98678b229e1c6c908bfc83ce3` |
| `docs/SCREENING-S2-ANCHOR-RESULT-v1.md` | `66c52e9ebf3011e3fc516a8b57ab6f8d5b1c222df40933e0c748e9823979e265` |
| `scripts/calib/semantic_judge_v21.py` | `a52ade5b9cc9bed5797e66995ee00b4de71b98568af5d806f5af661bfd868ffd` |
| `scripts/calib/treatments.py` | `700fb678a046b5cad210d55d1d0d873d69aa6c3f7f179d49e57fa2e00cd5c9c2` |
| `scripts/calib/runner.py` | `dacac2dc295904fd24a2eb6dfe08a8a98b5cb6298a987dd21bbe9c61064f30e6` |
| `scripts/calib/treatments_a1.py` | `2c17a75434065633a642af7aabf0361ced1f4ee3a76d7f3b57c666238dca9f62` |
| `scripts/calib/fixtures_a1.py` | `cbd9ab0a5fa0bc2a2a8d2cbc5315fe0544cc6b29d269f661fea8e5c4851c821d` |
| `scripts/calib/runner_a1.py` | `e29c06d4fcea9829ebebf902670f907f1120c5ea26dc41fe2536ebea461e6cc2` |
| `scripts/calib/run_a1.py` | `2c34c1b2e8b3e9aadc2a4268910989e16f6486c4c11c8956baa2b1a17f7ee6e0` |
| `scripts/calib/judge_a1.py` | `33642dee491e4ade07ace6d117aff3675e93f69e2801271f386c900bff904470` |
| `scripts/calib/analyze_a1.py` | `8f0623c76ea7eb2bb52b33b0aeb2148e0afd927453c0e03a4b5fe33c0412da15` |
| `data/calib/a1_matrix_v1.json` | `2034f6dc6fb187d9850a98ad8c226ea44e171abbe685e3a1e7be826f3e83355b` |
| `data/calib/a1_provider_manifest.json` | `eb1cb8d44edf47855978a47c3c4c2fd5514e56cae8f9466fdc4413e1d6b9fa96` |
| `docs/ABLATION-A1-PRE-REGISTRATION-v1.md` | `013ef19a5e9a8d07ff82e0f6db0514ab51235d62d7b7245e5433dd54d18c0914` |
| `docs/ABLATION-A1-MATRIX-v1.md` | `60584847e7ac82fd41301a2094d7324953f88da8eca7b25b7b8c67e2868a99a5` |
| `tests/unit/test_calib_a1.py` | `6052bf8dd98332b326dd47ead2987008d600ef844978e0669f155fc321daebd6` |

The freeze document itself is hashed separately after creation and is not self-listed.
