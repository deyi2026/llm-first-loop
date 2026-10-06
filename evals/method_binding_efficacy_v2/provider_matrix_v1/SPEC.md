# Subject-Binding Efficacy v2 — capability-aware provider preregistration

Status: FROZEN before provider execution.
Source goldset: ../GOLDSET-RESULT.json (PASS), commit 738aaed6ae1ca733bb323c43a130f7f877e667d9.

## Question
Does the current subject-binding cue improve purpose-level Method applicability decisions, especially on the weakest supported model, without reverse-risk harm or material cost regression?

## Frozen sample
- Use every certified B case from the qualified fresh goldset: 13 purpose-level near-miss SKIP cases.
- Use every certified C case: 8 reverse-risk APPLY cases.
- A/D controls are excluded from efficacy because they are ceiling/floor controls, not treatment opportunities.
- No case can be dropped/replaced after provider execution begins.

## Models / arms
- Strong: bare `deepseek-v4-flash`; canonical `deepseek/deepseek-v4-flash`.
- Weak: fully-qualified runtime ref `cognilocal/qwen3.8-flash-next`; canonical `cognilocal/qwen3.8-flash-next`.
- C0: `LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL` unset.
- C1: same code/config/model/prompt with that env set to `1`.
- Treatment must change only the `save_experience` lazy tool description; all other tool schema hashes must match.

## Matrix / order
- 21 certified cases × 2 models × 2 arms = 84 formal cells.
- A model×case pair is one block; its two arms run adjacent.
- 42 blocks are shuffled with seed 20261006.
- Arm-first is balanced globally 21 C0-first / 21 C1-first and nearly balanced within each model (11/10 vs 10/11).
- Each formal cell has an immutable row identity and attempt0 namespace.
- Each fresh DATA_DIR receives byte-copied snapshots of canonical runtime `data/providers.local.json` / `data/providers.json` before engine construction, so provider routing is isolated without collapsing to the L0 single-provider fallback. Snapshot SHA256 values are recorded per row; production files are read-only inputs.
- Mechanical technical failure only may trigger exactly one attempt1. Verdict/content is never inspected by the runner when deciding retry.
- Malformed applicability output with otherwise mechanically healthy provider/run settlement is an outcome (`OTHER`), not a retry reason.

## Provider-free gates before any formal row
1. Goldset RESULT verdict PASS and hash matches plan freeze.
2. All 21 case ids are certified and consist of B=13/C=8.
3. Surface probe for every model×arm: same tool names; only `save_experience` schema differs C0 vs C1; marker absent in C0 and present in C1.
4. Frozen-order/status namespaces fresh; no formal row identity consumed.
5. Runner fixture/compile/diff checks pass.

## Provider preflight
Before formal rows, one non-scored call per model×arm (4 total) must mechanically prove:
- exact canonical model, no fallback/truncation;
- run.end completed;
- provider calls opened=settled success;
- transport attempts opened=settled success and HTTP 200;
- request.meta / transport prepared evidence exists.
Preflight output content is not an efficacy outcome.

## Efficacy / safety gates
All metrics are computed only after all authorized formal cells are terminal.

Per model on B (n=13):
- `positive_flip`: C0 wrong, C1 correct.
- `negative_flip`: C0 correct, C1 wrong.
- `net_flip = positive_flip - negative_flip`.
- model efficacy PASS iff net_flip >= 3 (>= 3/13 = 0.2308 net accuracy gain) AND negative_flip <= 1.

Reverse-risk C (n=8), per model:
- C1 accuracy >= 7/8;
- new harm (C0 correct -> C1 wrong) <= 1;
- C1-C0 accuracy delta >= -1/8.

Mechanical safety, per model:
- OTHER_C1 <= OTHER_C0 + 1;
- technical retry count C1 <= C0 + 1;
- all selected latest cells must have exact model identity; any unresolved mechanically unhealthy cell prevents qualification.

Cost, per model (healthy latest rows only):
- mean total tokens C1/C0 <= 1.10;
- mean rounds C1 <= mean rounds C0 + 0.25;
- total tool calls C1 <= C0 + 2.
- wall-clock is diagnostic only, not a gate.

## Capability-aware disposition
- Both model efficacy PASS + reverse-risk/safety/cost PASS => `GENERAL_EFFICACY_QUALIFIED`.
- Weak PASS + Strong non-regression (B net_flip >=0) + all guardrails PASS => `WEAK_TARGETED_EFFICACY_QUALIFIED`.
- Strong PASS but Weak FAIL => `STRONG_ONLY_SIGNAL__NO_WEAKEST_MODEL_PROMOTION`.
- Neither model passes => `EFFICACY_NOT_QUALIFIED`.
- Any reverse-risk/safety/cost hard failure => `GUARDRAIL_BREACH__NO_PROMOTION`.

No p-value is a promotion gate at this n; paired exact/sign statistics are descriptive only.

## Boundaries
No production publish/restart/config edit, no Method lifecycle promotion, no prompt/binding tuning, no push. Experiment runs in an isolated worktree pinned to 738aaed6a and fresh per-attempt DATA_DIR namespaces. Canonical provider registry files are copied read-only into those namespaces as runtime assets. No interim efficacy aggregation.
