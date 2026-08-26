# Evidence Recoverability R4 — Production Consumption Holdout Result v1

Date: 2026-08-26
Frozen pack: `tests/fixtures/evidence_r4/frozen_v1.1.json`
Official frozen scorer: **FAIL**
Production rollout: **NOT ELIGIBLE**
A3: **STOPPED / excluded**

## Executive result

R4 v1.1 is the first fresh holdout that drove the real production Evidence control plane end to end after the R3 v1.1 consumption changes. The frozen scorer fails:

- 36/36 valid rows completed, 0 row-level infra failures;
- overall exact: **25/36 (69.4%)**;
- MiniMax exact: **11/18 (61.1%)**;
- DeepSeek exact: **14/18 (77.8%)**;
- non-refresh-seed source-once frozen metric: **28/30 (93.3%)**;
- K1 exact: MiniMax 2/3, DeepSeek 3/3;
- K2 exact: MiniMax 2/3, DeepSeek 3/3;
- K3 side-effect receipt: **6/6 exact, 0 duplicate side effects**;
- K4 current-change: **2/6 exact**, but **0 stale-as-current**;
- K5 historical stale: **1/6 exact**, while explicit historical access occurred in **5/6**;
- K6 UNKNOWN runtime snapshot: **6/6 exact**;
- transport EvidenceRef used as domain answer: **0/36**.

The frozen scorer result remains FAIL. No post-hoc threshold or scorer edit overrides it.

## Infra v1 invalid attempt

The first R4 real attempt was not behavioral data. Its runner passed internal `ToolRegistry.schemas()` directly to providers instead of production's OpenAI function-tool wrapper. Both providers rejected the request before model execution; all 36 rows had `source_execution_count=0` and `recovery=0`.

That attempt is archived under `data/audit/evidence_r4/infra_invalid_v1/`. The v1.1 amendment changed only the wire schema adapter, with fixtures, matrix, scorer, production Evidence and provider parameters unchanged. `frozen_v1.1.json` then governed the valid run.

## R3 safety/typing effects supported by R4

Several R2 failure modes did not reproduce:

1. **Transport/domain confusion**: R2 had a case where the model returned an `evidence://...` handle as the business receipt. R4: **0/36** transport-ref-as-domain answers.
2. **Stale as current**: R2 had four F6 stale-as-current outcomes. R4 K4: **0/6** stale-as-current.
3. **Side-effect duplication**: R4 K3: **6/6 exact and 0 duplicate executions**.
4. **UNKNOWN freshness over-blocking**: R4 K6: **6/6 exact** with recovery access and no stale block.

These are mechanical safety/typing signals and support the R3 v1.1 direction.

## Why the aggregate FAIL must not be translated directly into another production patch

Trace audit found two holdout-oracle confounds and one measurement confound.

### K4 current-value oracle is ambiguous

The intended target line was:

```text
R4-K4-CURRENT-VALUE: TEAL-908
```

but every current-version filler line was named `K4-new row ...`, while the task only said:

```text
Return the CURRENT R4-K4 value.
```

It did not name the target field. Several non-exact answers were `K4-new` or the projected `K4-new` content. Those outputs are wrong under the frozen oracle, but they do not prove a freshness-contract failure. Importantly, none selected the old token `AMBER-214` as current.

### K5 historical oracle overloads “FIRST observation”

The intended target line was:

```text
R4-K5-FIRST-OBSERVATION: IVORY-337
```

but all historical filler lines were named `K5-old row ...`, and the task asked for the value from the `FIRST observation`. Multiple models interpreted that as the first observed row and returned:

```text
K5-old row 0001: neutral holdout material ...
```

This persisted even after the production control plane correctly blocked stale default reads and the model explicitly retried with `allow_stale=true`.

Thus K5 demonstrates that the historical escape mechanism exists and is model-usable (5/6), while its exact-answer oracle is not clean enough to isolate consumption correctness.

### Raw `read_file` call count is not the original repeat-loop metric

R4's frozen `source_execution_count` treats all `read_file` actions equally. In R4-017, DeepSeek read the changed current file in three non-overlapping ranges (0-80, 80-160, 160-end). The scorer counted four source executions total and failed the `exactly two acquisitions` gate, even though the extra calls are range partitioning, not exact-repeat amnesia.

The historical root cause concerns same source + same arguments (or redundant overlapping/full reacquisition) without freshness change. A future gate must measure that directly rather than count every range read as a repeat.

## Diagnostic subset — not a rescoring

For the four less ambiguous seeds K1/K2/K3/K6, frozen exact results were:

- **22/24 (91.7%)** overall;
- MiniMax **10/12 (83.3%)**;
- DeepSeek **12/12 (100%)**.

The two remaining misses were formatting-level:

- K1: `third-break-value: LUMEN-5831` vs frozen exact `LUMEN-5831`;
- K2: `VEGA 731` vs frozen exact `VEGA-731`.

This diagnostic does not change official R4 FAIL. It only strengthens the case that K4/K5 fixture semantics dominate the remaining confirmatory uncertainty.

## Official frozen gates

Machine report: `data/audit/evidence_r4/score_real_v1.json`

PASS:

- infra 36/36 complete;
- zero transport-ref-as-domain;
- K1 provider exact floor/read recovery;
- K2 provider exact floor;
- K6 exact/recovery/no stale block;
- K3 zero side-effect duplicate and exact floor;
- K4 zero stale-as-current;
- K5 exact rows use explicit historical access.

FAIL:

- overall exact >=90%;
- provider exact >=15/18 each;
- source-once all non-refresh seeds;
- K2 forced search-usage >=4/6;
- K4 exact 6/6;
- K4 raw source-call count exactly two;
- K5 source-once all;
- K5 historical exact >=5/6.

## Artifact hashes

- valid runs: `9f107097381749eeda74a67d08b998d77ab15bf54534f66146d3dd5c785445d1`
- frozen score: `c1d43ba478f1a77e661dd118ae277a3cad40ff91e90829b37a086857d04b5e04`
- frozen pack v1.1: `4eaa2c5989271546a2af712c0699f68d01733e5f88a9a9aa8d7f76faf98156b7`

## Decision

R4 remains an official **FAIL**, and production enforce remains ineligible.

But the evidence does **not** justify reverting R3 or adding a duplicate Action Guard. The next step is a clean, narrower freshness-oracle holdout that:

1. uses neutral filler with no `old/new/first/current` lexical cues;
2. names the exact target field in the task;
3. pre-acquires Evidence mechanically before the first provider request, then mutates the source, directly reproducing the “old observation exists but raw context is gone” state;
4. measures exact same-args / redundant-overlap reacquisition rather than raw read count;
5. accepts read/search as alternative valid recovery paths rather than forcing one tool;
6. freezes all fixtures/matrix/scorer before any request.

R3 v1.1 production code remains unchanged pending that holdout.
