# Subject-Binding Efficacy v3 — Natural-Closeout Confirmatory Provider SPEC

Status: FROZEN before any confirmatory provider row.

## Sources
- Fresh holdout label qualification: `../confirmatory_holdout_v1/LABEL-RESULT.json` must be PASS.
- Development opportunity calibration: `../behavior_protocol_v2/RESULT.json` must be PASS.
- Only holdout rows dual-certified by both blind raters are eligible.
- Development instances are permanently excluded.

## Protocol
The formal behavior surface is the natural episode closeout used by development protocol v2. Each row receives current task, RESULT.md carrier, and one hydrated Method card, then must record Method use and save one lesson. C0 and C1 use identical code/model/prompt/case content; C1 changes only `LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL=1`, which appends the frozen subject-binding cue to the `save_experience` tool description.

Models:
- Strong: bare `deepseek-v4-flash`, canonical `deepseek/deepseek-v4-flash`.
- Weak: `cognilocal/qwen3.8-flash-next`, canonical same.

Decision mapping from the one successful `record_use` decision:
- positive: `applied | adapted`
- negative: `not_applicable | rejected`
- anything else / zero or multiple decisions: `OTHER`

Correctness:
- challenge intended SKIP => negative is correct.
- reverse-risk intended APPLY => positive is correct.

## Frozen matrix
- 23 dual-certified holdout cases: 17 challenge + 6 reverse-risk APPLY.
- 23 cases × 2 models × 2 arms = 92 formal cells.
- One model×case pair is an adjacent two-arm block.
- 46 blocks are shuffled with seed 20261024.
- Strong arm-first split 12 C0 / 11 C1; Weak split 11 C0 / 12 C1; global 23/23.
- Immutable row identity, fresh external state namespace per attempt.
- Mechanical failure only may trigger exactly one attempt1. Outcome/decision never triggers retry.
- Development or preflight outputs are never pooled into formal efficacy.

## Provider-free gates
Before formal provider execution:
1. holdout LABEL-RESULT PASS and dev RESULT PASS, hashes match freeze.
2. 23 selected IDs exactly equal dual-certified IDs; challenge=17, reverse-risk=6.
3. C0/C1 tool names identical; frozen binding marker absent in C0 and present in C1; only `save_experience` description is permitted to differ.
4. plan has 92 unique row IDs and exact adjacent arm pairs.
5. runner rejects missing `LFL_CANONICAL_RUNTIME_ROOT` before any status/data/matrix reservation.
6. scripts compile and provider-free fixtures pass.

## Non-scored provider preflight
Exactly one fresh call per model×arm (4 total) before formal row1. PASS requires exact canonical model, no fallback/truncation, provider/transport settlement success, HTTP 200, and completed run.end. Preflight content is not an efficacy outcome.

## Efficacy gate (challenge n=17 per model)
For each model:
- positive_flip = C0 wrong, C1 correct.
- negative_flip = C0 correct, C1 wrong.
- net_flip = positive_flip - negative_flip.
- efficacy PASS iff `net_flip >= 3` and `negative_flip <= 1`.

This is at least 3/17 = 0.1765 net paired improvement and is structurally attainable given development C0 opportunity.

## Reverse-risk gate (APPLY n=6 per model)
- C1 accuracy >= 5/6.
- new harm (C0 correct -> C1 wrong) <= 1.
- C1-C0 accuracy delta >= -1/6.

## Behavioral / mechanical safety
Per model:
- OTHER_C1 <= OTHER_C0 + 1.
- technical retries C1 <= C0 + 1.
- missing successful experience artifact C1 <= C0 + 1 and C1 artifact success >= 22/23.
- all latest selected cells exact model identity, binding assertion matches arm, settlement success, run.end completed.
- any unresolved mechanically unhealthy cell prevents qualification.

## Cost gate
Per model, latest mechanically healthy rows only:
- mean total tokens C1/C0 <= 1.10.
- mean rounds C1 <= mean rounds C0 + 0.25.
- total tool calls C1 <= C0 + 2.
- wall-clock diagnostic only.

## Disposition / production authorization
- Both model efficacy PASS + all guardrails PASS => `GENERAL_EFFICACY_QUALIFIED` and production promotion authorized.
- Weak efficacy PASS + Strong challenge net_flip >= 0 + all guardrails PASS => `WEAK_TARGETED_EFFICACY_QUALIFIED` and production promotion authorized.
- Strong PASS but Weak FAIL => `STRONG_ONLY_SIGNAL__NO_WEAKEST_MODEL_PROMOTION`; no production promotion.
- Neither passes => `EFFICACY_NOT_QUALIFIED`; no production promotion.
- Any guardrail hard failure => `GUARDRAIL_BREACH__NO_PROMOTION`.

No interim efficacy aggregation. No prompt/binding tuning after row1. Production publish/restart/default promotion may occur only after a frozen result explicitly sets `production_promotion_authorized=true` and current-main reconciliation/qualification succeeds. Remote push remains unauthorized.
