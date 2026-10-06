# Subject-Binding v3 — C0-only Development Difficulty Calibration

Status: FROZEN before provider preflight/formal execution.

## Purpose
Measure control difficulty/opportunity only. This is not treatment efficacy.

## Sample
- exactly the 23 dual-certified intended-SKIP challenge cases from `../LABEL-RESULT.json`
- development instances are permanently non-confirmatory
- 4 preregistered abstract families; one uncertified case `v3d-B10` is excluded and never rescued

## Models / arm
- Strong: `deepseek-v4-flash` / canonical `deepseek/deepseek-v4-flash`
- Weak: `cognilocal/qwen3.8-flash-next`
- arm: **C0 only**; `LFL_METHOD_SUBJECT_BINDING_EXPERIMENTAL` must be unset
- C1 is forbidden on all development instances

## Matrix / mechanics
- 23 cases × 2 models = 46 formal cells
- case blocks shuffled with seed 20261006; Strong/Weak run adjacent, model-first alternates by block
- every identity has attempt0 and at most one attempt1 triggered only by mechanical failure
- malformed applicability output is an outcome, never a retry trigger
- explicit canonical runtime root + `.env` + provider registries must pass before O_EXCL reservation
- per-attempt DATA_DIR receives read-only byte-copied provider registry snapshots
- exact model identity, provider settlement, HTTP200 transport, prepared evidence, and completed run.end are mechanical health requirements

## Family viability
Computed only after all 46 authorized cells are terminal.

For each family, on **Weak C0** dual-certified rows:
- viable iff `0.45 <= accuracy <= 0.80`
- family also rejected if Strong=1.00 and Weak=1.00 (opportunity-free)
- OTHER is an outcome and counts incorrect

Strong is diagnostic. Viability selects only the **abstract family**, never the development instances.

At least one viable family is required to proceed to fresh confirmatory holdout construction. If none are viable, stop provider execution and redesign provider-free family templates; do not run C1 on dev.

## Boundaries
No C1 dev calls, no confirmatory case construction from individual dev errors, no production mutation, no Method promotion, no prompt/binding edit, no publish/restart, no push.
