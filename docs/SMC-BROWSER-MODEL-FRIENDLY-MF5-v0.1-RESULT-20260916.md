# SMC Browser Model-Friendly Semantic Operation — MF-5 v0.1 Result — 2026-09-16

Status: **COMPLETE / NOT QUALIFIED / EFFICIENCY SIGNAL POSITIVE / MF-6 DEFERRED**

Candidate code: `bb0d0ab0a43c37d7c1e204232b39a0cb17b60782`

Shared Browser backend baseline: `9734d57c7997bb1f7585c8311029eba25175c51a`

Protocol: `evals/browser_smc_model_friendly_operation_mf5/PROTOCOL.v0.1.md`

Measured result set: `evals/browser_smc_model_friendly_operation_mf5/results/MF5-ORNITH-AB-v0.1/`

## 1. Verdict

MF-5 v0.1 is **not qualified** under its frozen conjunctive Gate.

The important split is:

- **efficiency gate: PASS**;
- **hard correctness/contract gate: FAIL**;
- therefore **overall gate: FAIL**;
- MF-6 independent confirmatory **must not start** from this interface identity.

This is not evidence that the model-friendly direction failed. It is evidence that MF-2/MF-3 removed substantial interface tax while the short input language still contains one high-frequency grammar trap that prevents stable first-call use.

## 2. Frozen A/B identity

Both arms used the same current Browser mechanical backend, exact/version guards, typed Predicate execution, single-dispatch action path, ActionReceipt persistence, MF-4 decision-boundary halt behavior, local Ornith runtime, 12-round ceiling, fixtures and user prompts.

Only the model-facing contract differed:

| Arm | Model-facing input | Model-facing normal result |
|---|---|---|
| A | legacy `clauses` | full bounded-operation receipt |
| B | short `steps` | compact receipt + exact `receipt_ref` / `diff_ref` hydration |

The 12 rows were paired/interleaved rather than running all A then all B. Each of the three tasks had two repeats per arm. No measured row was replayed, repaired in place, or selectively discarded.

## 3. Gate result

| Metric | A | B | B vs A |
|---|---:|---:|---:|
| External task oracle | 3/6 | **5/6** | +2 tasks |
| Agent rounds | 72 | **64** | **-11.1%** |
| Support calls (`get_tool_schema + read_evidence`) | 15 | **9** | **-40.0%** |
| Model-visible operation chars | 61,866 | **22,887** | **-63.0%** |
| Input tokens | 327,462 | **207,296** | **-36.7%** |
| Output tokens | 11,137 | **7,679** | **-31.0%** |
| Cache-hit tokens / input tokens | 86.47% | **89.82%** | +3.35 pp |
| SRTA | 4.5 | **4.0** | -11.1% |
| Operation contract failures | **18** | 29 | worse in B |
| Automatic mutation retry | 0 | 0 | invariant preserved |
| Direct atomic Browser calls | 0 | 0 | invariant preserved |
| Runtime task-completion judgment | 0 | 0 | invariant preserved |
| Operation execution errors | 0 | 0 | backend did not crash |

Frozen Gate output:

- `efficiency_pass = true`
- `hard_pass = false`
- `pass = false`

The efficiency result is therefore a valid positive signal, not a release qualification.

## 4. Paired task results

| Pair | A | B | Observation |
|---|---|---|---|
| click_commit r1 | PASS / 12 rounds | PASS / 12 rounds | correctness preserved; no round gain |
| fill_submit r1 | PASS / 12 | PASS / 12 | correctness preserved; B avoided schema/evidence support calls in this row |
| delayed_wait r1 | FAIL / 12 | **PASS / 4** | strongest positive trajectory signal |
| delayed_wait r2 | FAIL / 12 | FAIL / 12 | model-facing stability still incomplete |
| fill_submit r2 | FAIL / 12 | **PASS / 12** | B recovered task correctness but not round ceiling |
| click_commit r2 | PASS / 12 | PASS / 12 | correctness preserved; contract repair churn remained |

The repeat split matters: one 4-round delayed-wait success is not sufficient to call the interface stable because the second repeat failed.

## 5. Failure taxonomy

### 5.1 Legacy A

A produced 18 model-facing contract failures, spread across the complex clause/target grammar:

| Failure | Count |
|---|---:|
| `object_target_fields_mismatch` | 10 |
| `object_target_contract_mismatch` | 4 |
| `mutate_clause_fields_mismatch` | 2 |
| `identity_fields_mismatch` | 1 |
| `clause_kind_not_supported` | 1 |

This matches the original Interface Tax hypothesis: the old surface gives the model too much protocol structure to reproduce correctly.

### 5.2 Model-friendly B

B produced 29 contract failures, but they are much more concentrated:

| Failure | Count | Share of B failures |
|---|---:|---:|
| `short_operation_not_supported` | **25** | **86.2%** |
| `steps_count_out_of_bounds` | 3 | 10.3% |
| `click_step_fields_mismatch` | 1 | 3.4% |

All 25 `short_operation_not_supported` failures came from the same semantic grammar asymmetry: every normal mutation uses a `do` discriminator, while wait is exposed as a special `{wait: ..., within_ms: ...}` shape. Ornith repeatedly produced the natural symmetric form `do:"wait"`.

The dominant rejected shape alone occurred 16 times:

```json
{
  "steps": [
    {
      "do": "wait",
      "wait": {
        "target": {"kind": "button", "name": "Commit choice"},
        "property": "exists",
        "value": true
      },
      "within_ms": 5000
    }
  ]
}
```

Additional rejected multi-step calls contained the same `do:"wait"` form. The other three B failures serialized `steps` as a JSON string after repeated contract-repair churn; one call mixed wait fields into a click step. Those should not be mechanically accepted as a general coercion rule.

## 6. Strong counterexample: delayed_wait r1

B row 6 completed the waiting task in four rounds with exactly three successful semantic operations:

1. `do:"navigate"`;
2. canonical typed wait on the exact named button `Finalize after ready`, property `enabled == true`, within 60 s;
3. exact click on the same named button.

No schema lookup, Evidence hydration, retry, fuzzy target, automatic rebind, or program task-completion judgment was needed.

This row demonstrates that the current primitives are sufficient and that the compact result does not inherently starve the model of information. The main instability is whether the model lands on the canonical short grammar and the right exact predicate trajectory consistently.

## 7. Architectural interpretation

MF-5 supports four conclusions.

### 7.1 Interface Tax reduction is real

B reduced support calls, model-visible operation bytes, input tokens, output tokens, aggregate rounds and SRTA while improving the task oracle from 3/6 to 5/6.

### 7.2 The current short language is not yet internally regular

The special wait discriminator is the dominant B failure source. A model-friendly language should not require the model to remember that five operations use `do`, but wait alone uses a different top-level discriminator.

### 7.3 Do not solve this by weakening exactness

The repair should **not** add fuzzy target matching, inferred document targets, best-match ranking, auto retry, auto rebind, automatic latest/snapshot selection, or program-side task completion. Those are unrelated to the observed dominant failure.

### 7.4 Do not solve this by merely raising max rounds

Several failed rows already exhausted 12 rounds. Prior 16-round diagnostics also showed that more rounds do not guarantee convergence. The next intervention should reduce contract-repair loops, not extend them.

## 8. Required next identity: MF-5.1

MF-5 itself is closed. Any interface change requires a fresh qualification identity.

Recommended MF-5.1 change is deliberately narrow:

1. make the provider-facing grammar use a **single uniform `do` discriminator**, including `do:"wait"`;
2. canonical wait surface should directly expose exact `target`, typed `property`, optional/defaulted `operator`, `value`, and `within_ms`;
3. keep exact target `kind + name` semantics and optional role; do not infer missing identities;
4. keep the existing nested wait form only as an internal compatibility path if needed by deterministic historical tests, not as the canonical provider-facing grammar;
5. do not accept stringified `steps` or arbitrary click+wait hybrids as coercions;
6. add one concise tool-local canonical wait example if schema alone still leaves the grammar ambiguous; do not expand the universal prompt.

Example target wire:

```json
{
  "steps": [
    {
      "do": "wait",
      "target": {"kind": "button", "name": "Finalize after ready"},
      "property": "enabled",
      "value": true,
      "within_ms": 60000
    }
  ]
}
```

This is mechanical syntax normalization only. It does not transfer semantic authority from model to program.

## 9. MF-5.1 qualification discipline

The next protocol should separate two questions that MF-5 v0.1 coupled too tightly:

- **Treatment hard qualification:** B must independently achieve 6/6 task oracle, zero operation contract failures/errors, zero auto retry/rebind/fuzzy/direct-atomic/task-completion violations.
- **Paired comparative evidence:** A remains a contemporaneous baseline for rounds/support-calls/model-visible bytes/tokens/SRTA, but A does not need to satisfy the treatment's hard qualification gate.

This avoids a methodological problem in MF-5 v0.1: the legacy baseline was required to be 6/6 with zero contract failures even though the purpose of the experiment was partly to measure its protocol friction. The old Gate remains authoritative for MF-5 v0.1 and is **not** retroactively changed.

If MF-5.1 treatment hard qualification passes, run a fully fresh independent MF-6 confirmatory repeat before calling the interface stable.

## 10. Evidence identity

Top-level measured artifacts:

| Artifact | SHA-256 |
|---|---|
| `execution-manifest.json` | `0632b343311ba5422f00713952055edd0c76180c85b838101e308d42d6605ef5` |
| `plan.json` | `2423d5dddf777ef27a8def4a2c2b275f81a4b948457f95c991884aee0d4e429d` |
| `results.jsonl` | `ba68ecb1a292483f0528c79fdf0e7c4fc026f5d84f508a82513198992a0e96df` |
| `qualification-gate.json` | `cfd5d1fd4212830bbbf777ba3e878688e9172caba62dc3a8a1d3a6be157c092e` |

No production deployment, service restart, cloud fallback, or second local model was used by this qualification.

## 11. Post-result architecture correction: preserve model cognition

A later architecture ruling sharpens the interpretation of this result: Semantic Operation should be treated as the model's **actuation mechanism**, not as a reasoning language the model must adopt.

MF-5 B reduced bytes/tokens/support calls, but several failed trajectories still diverted model reasoning into interface repair: the model explicitly reasoned about whether wait needed an operator, whether wait-only calls were supported, whether it should combine wait with navigate/scroll, and when to request schema. Those turns did not represent useful task reasoning; they were **protocol-induced reasoning** created by the interface.

This means the remediation target is broader than “make `wait` use the same discriminator”. `d6ec0113` fixes the concrete grammar asymmetry, but the next qualification must ask:

> Can the model reason about the task normally, decide an action normally, and then invoke Semantic Operation without reorganizing its thought process around the tool contract?

The desired interaction is:

```text
model: reason normally -> decide "wait until button enabled"
tool call: natural semantic actuation
runtime: exact ground -> typed predicate -> bounded poll -> receipt
model: continue normal task reasoning
```

not:

```text
model: decide to wait -> reason about DSL fields -> guess schema -> repair call -> retry grammar -> return to task
```

Future qualification should therefore retain the existing correctness/safety/efficiency metrics and add a turn taxonomy with a hard target of zero `protocol_repair` turns after a correct semantic intent has been formed. This does not suppress model reasoning; it distinguishes productive task reasoning from reasoning forced by API friction.

MDEH remains valid but is reinterpreted as an **optional execution handoff boundary**, not a required model planning representation. The runtime may batch multiple actions only when the model has naturally already decided them; it should never pressure the model to pre-plan more steps merely to reduce round trips.
