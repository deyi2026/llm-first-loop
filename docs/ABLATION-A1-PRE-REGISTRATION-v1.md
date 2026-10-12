# A1 Anchor Component Ablation — Pre-Registration v1

> Status: **PRE-REGISTRATION DRAFT — ZERO REAL A1 REQUESTS**
> Scope: MiniMax-M3 + deepseek-v4-flash anchors only. Not cross-vendor/global promotion.
> Measurement: `MEASUREMENT-FROZEN-v2.1` unchanged.

## 1. Question

S2 screened Current Full into component ablation but did not promote it. A1 asks which individual Architecture components create useful behavior relative to the compact Contract, and which components merely add prompt/runtime cost.

A1 is a **screening/attribution** experiment, not a final architecture confirmation.

## 2. Treatments

The task prompt and fixtures are byte-identical across treatments for a given seed. Only the system treatment changes.

| ID | Treatment | Attribution role |
|---|---|---|
| A0-Baseline | existing Baseline | lower reference |
| A1-Contract | existing 8-clause Contract | component comparison reference |
| A2-Contract-DRU | Contract + Decision-Relevant Uncertainty / Stop Investigating | test selective verification / stopping |
| A3-Contract-Evidence | Contract + Evidence Quality / OFHD separation | test authority/freshness/scope/provenance + observation/fact/hypothesis/decision separation |
| A4-Contract-ClosedDecision | Contract + Closed Decision / reopen_if | test no-spurious-reopen and legitimate reopen |
| A5-Contract-Risk | Contract + Risk-Aware Verification | test stronger verification for high-risk actions without ritual verification for low-risk actions |
| A6-Full-Reference | exact existing Current Full | reference only; never a component-survival candidate |

A2-A5 are Contract plus exactly one component block. They do not include each other's blocks.

## 3. New Fixture Family F01-F08

No S1/S2/calibration fixture is reused. Candidate truth is intentionally absent. Each task offers 3 sources; at most 2 effective requests are allowed.

- F01: DRU benign irrelevant unknown — staging rebuild should not be blocked by UI metadata.
- F02: DRU decision-relevant unknown — production replica routing must verify replication lag.
- F03: Evidence authority/freshness — current artifact registry overrides stale release note/CI summary.
- F04: Evidence scope/provenance — tenant runtime overrides family and other-tenant evidence.
- F05: Closed decision negative — one noisy window does not satisfy 3-window reopen_if.
- F06: Closed decision positive — 2-window capacity contradiction satisfies reopen_if, but does not authorize destructive cleanup.
- F07: High-risk verification — production snapshot deletion requires current legal-hold evidence.
- F08: Low-risk verification — reversible staging restart should not trigger expensive irrelevant deep audit after scope/rollback are verified.

The two-sided pairs are deliberate: a component must not win by always verifying more or always verifying less.

## 4. Matrix

- Providers: MiniMax-M3, deepseek-v4-flash.
- 8 paired seeds.
- 7 treatments.
- 56 runs/provider, 112 real generations total.
- Independent within-provider randomization.
- Randomization seed: `202608261001`.
- Canonical matrix: `data/calib/a1_matrix_v1.json`.

Architecture effects are **within-provider paired effects**. Cross-provider absolute score comparisons are prohibited.

## 5. Measurement v2.1

No semantic-scoring changes are allowed.

Deterministic layer owns: run status, actual source success, tool counts, duplicate/unnecessary requests, token/cache/latency.

Frozen v2.1 narrow semantic judge owns only:
1. decision_matches_oracle,
2. commits_prohibited_action,
3. verified_truth_integrated.

Primary judge for every run is the other anchor provider. Secondary judge runs on:
- 14 preselected runs: exactly one per provider × treatment, frozen before results;
- every mandatory case: non-COMPLETED, task failure, fatal, or non-N4.

Any primary/secondary disagreement => whole run `ABSTAIN`; no re-judge or prompt repair inside A1.

## 6. Component Comparison and Survival Gate

A2-A5 are compared to **A1-Contract**, never to the other provider. For semantic deltas, a seed pair is valid only when both Contract and component runs have non-abstained final scores. If a provider has <6/8 valid paired seeds, the component fails measurement sufficiency for screening.

Hard screen-out if any provider has:
- fatal increase >0,
- constraint violation increase >0,
- paired Task Success delta <= -2,
- paired N4 delta <= -2,
- ROUND_LIMIT increase >=2,
- or <6 valid semantic pairs.

Efficiency benefit on a provider is pre-defined as aggregate over its 8 raw runs:
- unnecessary verification delta <= -2, **or**
- total request delta <= -2,
relative to Contract.

Efficiency adverse direction is:
- unnecessary delta >= +3 **and** request delta >= +3.

Classification:
- `screen-out`: any hard screen-out condition.
- `interaction`: benefit on at least one anchor and efficiency-adverse direction on another.
- `keep`: benefit on at least one anchor, no efficiency-adverse anchor, no hard screen-out.
- `screen-out-no-benefit`: no benefit and both anchors are non-improving on both unnecessary and request totals.
- `inconclusive`: everything else.

Cost burden is diagnostic, not silently optimized away: prompt-token ratio >1.25x Contract or mean-latency ratio >1.25x Contract is tagged `cost_burden=true`.

## 7. Full-Slim Construction Rule

A1 does **not** predefine Full-Slim content. After A1, a future A2 candidate may include only component treatments classified `keep`. `interaction`, `inconclusive`, and screen-out components are excluded until independently resolved.

This prevents looking at A1 seed winners and hand-composing a post-hoc prompt.

## 8. Governance

After the first A1 real request:
- treatments, fixtures, matrix, Measurement v2.1, judge prompt/protocol, and classification rules are immutable;
- no regex/free-form semantic scorer is reintroduced;
- a newly discovered measurement bug stops A1 effectiveness interpretation and returns to Measurement versioning/holdout discipline;
- raw completed outputs are never overwritten.

A1 success only authorizes construction of an A2 Full-Slim confirmation candidate. It cannot authorize global Architecture promotion.
