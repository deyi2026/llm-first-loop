# Subject-Binding Efficacy v2 - Fresh Goldset preregistration

Status: FROZEN by operator delegation ("你来推进") on 2026-10-05.

## 0. Scope

This phase qualifies the measurement pool for the next efficacy experiment. It does not run a C0/C1 provider matrix.

- provider_calls = 0.
- Do not change gen177, subject-binding text, Method lifecycle, or production config.
- The v1 40-case pool is regression-only and cannot be a promotion pool.
- IQ-CTOR-v2 is the constructor qualification source. Its limitation remains: model-by-model agreement is established, human anchor is not.
- PASS here means only that the fresh goldset may be used by a separately preregistered efficacy SPEC.

## 1. Freshness

1. Every subject Method is outside the v1 top-20 card universe.
2. Every new task is exact-SHA checked against v1 pool and IQ-v1 task text. Any hit fails construction.
3. B/C tasks are newly authored and never copy old trigger text. A/D controls may use fresh Methods' own/source triggers, but still cannot exactly match an old-pool task.

## 2. Frozen 40-case layout

| Cell | n | intended | role |
|---|---:|---|---|
| A | 8 | APPLY | easy-positive ceiling control |
| B | 16 | SKIP | H+: purpose-level near miss |
| C | 8 | APPLY | H-: reverse-risk APPLY under paraphrase |
| D | 8 | SKIP | easy-negative floor control |

B hard constraints:

- Every row has purpose_divergence and construction_source.
- construction_source differs from subject_method_id.
- SKIP is justified only by purpose/discriminator mismatch. Bigram/Jaccard never assigns the label.
- Lexical similarity is diagnostic only.

C hard constraints:

- The task preserves the subject Method's Trigger/Discriminator conditions but does not copy its trigger.
- APPLY is required for certification; these rows detect over-filtering.

## 3. Blind scoring

R1/R2 see only opaque_id + task + Method card. They must not see cell, intended, source, or purpose_divergence.

Question: Assume you are executing the task and only have this Method card. Is the card applicable? APPLY means adopting it would materially change/correct execution; SKIP means it is not applicable. Give a one-line reason comparing task purpose with Method purpose.

Each score row contains opaque_id, verdict (APPLY or SKIP), and a non-empty one-line reason.

## 4. Qualification gates

One-shot analysis only; no interim deletion, replacement, or relabeling.

| Gate | PASS |
|---|---|
| raw agreement | >= 0.85 |
| Cohen kappa | >= 0.70 |
| A certified | >= 7/8 |
| B certified / H+ | >= 12/16 |
| C certified / H- | >= 6/8 |
| D certified | >= 7/8 |
| exact freshness | 40/40 fresh |
| B purpose metadata | 16/16 complete |
| structural reachability | provisional future challenge effect +0.20 => need=ceil(.20*16)=4; require H+ >= 8 and H- >= 6 |

Certified means R1 and R2 both give the intended verdict. Disagreements are not rescued by post-hoc adjudication.

## 5. Ceiling, floor, reverse-risk

- A is the ceiling control; below 7/8 => HOLD.
- D is the floor control; below 7/8 => HOLD.
- C is reverse-risk; below 6/8 => HOLD.
- B is the treatment-opportunity stratum. A future efficacy SPEC should use B paired transitions as a primary efficacy surface instead of diluting the signal with A/D saturation.

## 6. Cost scope for the later efficacy SPEC

This goldset does not freeze provider-cost thresholds. The later SPEC should default to token/round/request/tool-call as primary cost metrics. Wall-clock is secondary unless tight paired or AB/BA blocking controls transport variance.

## 7. Freeze discipline

- Builder, sealed mapping, blind sheet, and scorer template hashes are recorded.
- Scorers must not read goldset_sealed.json before both answers are persisted.
- Any proxy-model rater is recorded as a DEV and must not be described as human inter-rater evidence.
- After goldset qualification, stop. Do not automatically start provider execution.
