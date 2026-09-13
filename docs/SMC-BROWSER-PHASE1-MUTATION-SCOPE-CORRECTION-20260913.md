# SMC Browser Phase 1 — Mutation Version-Scope Correction

Status: **QUALIFIED_CORRECTION**

Baseline before correction: `23947f8185bd710d590d47cc85039038481e7c28`

Implementation commit: `4461e64fc924ef265dad2a09cb6f1a85a3407326`

This correction supersedes only the **model-facing Phase 1 mutation `version_scope` contract** from the earlier B-QUAL result. It does not rewrite the historical B-QUAL evidence, the real-model smoke evidence, or the strict B-STALE semantics.

## 1. Triggering evidence

The frozen real-model smoke in `evals/browser_smc_ab/results/SMOKE-v0.1/` completed 6/6 valid rows and produced a repeated mechanical blocker:

- SMC task oracle: **0/3 PASS**;
- legacy task oracle: **3/3 PASS**;
- all three SMC runs adopted the SMC Browser tools;
- SMC terminal ActionReceipts: **9 rejected, 0 successful physical dispatch**;
- repeated rejection: `version_precondition_stale:different_snapshot_same_generation`;
- `automatic_retry_performed=true`: **0**.

The runtime behavior was internally consistent but the mutation contract was not usable. Mutation correctly performs a fresh pre-dispatch observation, while strict snapshot versioning correctly declares a different snapshot identity stale. Therefore a mutation submitted with `version_scope=snapshot` can be valid according to the old model-facing contract yet mechanically fail merely because the mandatory guard observed the world again.

The correction removes that impossible type combination rather than weakening stale checking.

## 2. Corrected contract

Phase 1 mutation scopes are now:

| Verb | Qualified mutation `version_scope` |
|---|---|
| `click` | `object` |
| `fill` | `object` |
| `select` | `object` |
| `scroll` | `object` |
| `navigate` | `resource` |

`snapshot` remains a valid **read-only observation/version-assessment semantic** for retained snapshots, exact diff/version facts, and B-STALE comparisons. It is no longer a Browser mutation precondition scope.

The following boundaries remain unchanged:

- mandatory fresh pre-dispatch observation;
- exact Semantic ID / scope re-resolution;
- stale or indeterminate precondition → `rejected`;
- no selector/XPath/coordinate/backend-node model input;
- no target substitution or best-match recovery;
- no automatic mutation retry/replay;
- duplicate `action_id` never dispatches twice;
- ActionReceipt status is not task completion.

## 3. TDD evidence

The correction was introduced with a deliberate red test first.

Before the runtime/profile/schema change, four directed checks failed:

1. every mutation verb using `version_scope=snapshot` was expected to reject **before capture**, but the old runtime accepted it and reached B-STALE;
2. Profile verb scopes still exposed `snapshot`;
3. canonical `SemanticAction` schema still exposed `snapshot`;
4. lazy provider contract did not state the verb-to-scope mapping.

After the correction:

- all five mutation verbs reject `snapshot` with `version_scope_mismatch` before pre-dispatch capture;
- the qualified positive paths still dispatch exactly once with `object` / `resource`;
- runtime `_MUTATION_CONTRACT`, Profile JSON, canonical schema and model-facing Browser tool surface are mechanically cross-checked for alignment;
- object mutation supplied with `resource` is rejected before capture;
- navigate retains exact page semantic-root binding under `resource` scope.

Focused action/spec/qualification tests: **43 PASS**.

Expanded Browser/SMC/schema adjacency: **179 PASS**.

## 4. Real Chrome qualification

All five Browser live suites were rerun after the correction.

| Suite | Result | Result SHA256 |
|---|---:|---|
| Navigation | 8/8 PASS | `81168752968887f26dbb741033bf97d6fcbea25730a79d3d8da4e09f9edf0c80` |
| SemanticDiff | 15/15 PASS | `b0af595c5c392de494b243127f9ca60ae57624fd9f19a2dd04370680dd475915` |
| Predicate / Wait | 12/12 PASS | `41b7ca20d9bbc938b4c0254660fddc16a15c78aac56da1f7eff90bae01732828` |
| VersionPressure / B-STALE | 13/13 PASS | `51268ff3b5b9e31a92a167425a18746e01310749fa4b3b0f3c19dd2613d2d2ae` |
| Mutation / ActionReceipt | 19/19 behavior + 9/9 safety | `1c017ad8779450f2e5b2a75ab6e0af253350ad9345f88ca3c046737ea529c821` |

The first four result hashes are unchanged from their previously qualified runs. This is direct evidence that perception, identity, diff, wait and strict version-pressure semantics were not altered by the mutation contract correction.

The Mutation / ActionReceipt live suite adds two correction-specific facts:

- real `navigate + snapshot` is rejected with `version_scope_mismatch` and the page URL does not change;
- the model-facing `browser_action.version_scope` enum contains only `object | resource`.

The same run still passes click/fill/select/semantic-object scroll, resource navigation, stale rejection, same-name replacement no-rebind, duplicate action-id prevention, transport-ambiguity no-replay, popup boundary facts, append-only receipts, privacy checks and mock-keychain safety.

## 5. Repository gates

Before the implementation commit:

- Ruff: PASS;
- Pyright: **0 errors / 0 warnings / 0 informations**;
- whole-tree security: **1684 tracked files PASS**;
- full `scripts/ci_gate.sh`: **PASS**, including tier0 and full xdist.

A final committed-state rerun is required after this documentation is committed. This document is not itself the final A/B conclusion.

## 6. Non-claims

This correction does **not** claim or introduce:

- weaker snapshot staleness semantics;
- hidden refresh or latest-snapshot selection;
- mutation retry/replay;
- selector fallback or semantic target substitution;
- root-level page/document/frame/region scroll;
- vision-only perception or native browser/OS chrome control;
- semantic task-completion judgment.

## 7. Next qualification boundary

The prior A/B v0.1 results remain immutable blocker evidence and must not be pooled with a corrected run.

The next experiment must use a **new A/B protocol identity**, fresh sessions/browser profiles/data dirs/action IDs, and a freshly frozen capability/source manifest. It should first run a paired smoke. Expansion is allowed only if the SMC arm demonstrates at least one successful physical dispatch and the task oracles are no longer mechanically blocked by mutation version-scope selection.
