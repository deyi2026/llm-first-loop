# SMC Browser Cognition-Preserving Semantic Actuation — MF-5.2 Plan — 2026-09-16

Status: **DESIGN / QUALIFICATION PLAN / NO LIVE RUN YET**

Design authority: `docs/SMC-MODEL-FRIENDLY-SEMANTIC-OPERATION-DESIGN-v0.1-20260916.md`

Prior evidence: `docs/SMC-BROWSER-MODEL-FRIENDLY-MF5-v0.1-RESULT-20260916.md`

Current syntax regularization anchor: `d6ec0113` (`do:"wait"` regularization only)

## 1. Question

Can the model keep its ordinary task reasoning behavior and invoke Semantic Operation only at the point where it has already decided to act, while the runtime absorbs grounding/version/polling/dispatch/receipt mechanics without creating a new tool-language reasoning burden?

The experiment is **not** a test of whether the model can learn a Semantic DSL.

The desired relation is:

```text
normal task reasoning
  -> model decides an action
  -> minimal semantic actuation call
  -> strict mechanical runtime execution
  -> compact factual result
  -> normal task reasoning resumes
```

## 2. Architecture invariants

The treatment must preserve all of these:

1. model owns task interpretation, strategy, target choice, action choice and task completion judgment;
2. runtime owns exact grounding, scope/version checks, bounded polling, single dispatch, post-observation, diff and durable receipts;
3. no fuzzy/best-match/automatic target selection;
4. no automatic latest/rebind/stale repair;
5. no mutation auto-retry/replay;
6. no program task-completion judgment;
7. undeclared structural transitions halt;
8. one-action calls are first-class; batching is optional and only covers actions already decided by the model;
9. no universal prompt that tells the model to adopt a special Semantic Operation thought process.

## 3. What “cognition-preserving” means operationally

The qualification must not depend on privileged access to hidden chain-of-thought. Hidden/internal reasoning may be retained as diagnostic evidence when the local runtime exposes it, but it is **not** a release Gate.

Instead, use observable behavior proxies.

### 3.1 Productive observable behavior

- direct valid semantic actuation after the model decides to act;
- task-relevant evidence inspection when the previous compact result is insufficient;
- a new semantic decision after a real SDB/halt;
- one-action calls when the model naturally wants feedback before deciding again;
- multi-action MDEH only when the declared later actions were already semantically determined.

### 3.2 Protocol-induced behavior

Count as `protocol_repair` when observable evidence shows that task progress stopped because of tool-language friction, for example:

- `get_tool_schema` caused by rejection of an otherwise semantically appropriate action;
- repeated calls expressing the same semantic intent with only grammar/shape changes;
- contract rejection followed by another call whose only material change is protocol scaffolding;
- adding/removing irrelevant operations solely to make a tool grammar accept a call;
- converting an action into a larger pre-planned batch only because the interface appears to require batching;
- repeated provider-contract failures such as unsupported discriminator/field shape with no change in task semantics.

Do **not** count as protocol repair:

- exact target not found and the model chooses a different strategy;
- ambiguity requiring a genuine model choice;
- stale/version halt requiring a new semantic decision;
- predicate deadline/indeterminate result requiring task-level reconsideration;
- evidence inspection needed because the next decision genuinely depends on broader world context.

## 4. Treatment surface

Provider-facing concepts should be ordinary action affordances, not a planning language.

Illustrative canonical actions:

```json
{"steps":[{"do":"navigate","url":"..."}]}
```

```json
{"steps":[{"do":"set_text","target":{"kind":"input","name":"Project code"},"text":"AB-7319"}]}
```

```json
{"steps":[{"do":"wait","target":{"kind":"button","name":"Finalize after ready"},"until":"enabled","within_ms":60000}]}
```

```json
{"steps":[{"do":"click","target":{"kind":"button","name":"Finalize after ready"}}]}
```

`steps` is a transport container, not a required multi-step plan. A one-element list is normal.

The runtime may compile `until:"enabled"` mechanically to the qualified Predicate representation. The model should not need to state `property=enabled, operator=eq, value=true` unless that extra expressiveness is semantically necessary.

## 5. Qualification matrix

Start from the same 3 tasks x 2 repeats used by MF-5 so the new evidence remains comparable:

- `click_commit` x2;
- `fill_submit` x2;
- `delayed_wait` x2.

Freeze before model execution:

- exact code SHA;
- exact provider tool schema/description SHA;
- Ornith runtime identity and concurrency 1/1;
- task prompt hashes;
- fixture hashes;
- max rounds = 12;
- fresh session/DATA_DIR/Chrome profile per row;
- no replay or in-place repair;
- no fallback;
- same external task oracle.

A contemporaneous legacy arm may be kept for comparative metrics, but treatment release qualification must stand on its own hard Gate.

## 6. Hard Gate

All conjunctive for the treatment arm:

- external task oracle: 6/6;
- first semantic actuation contract-valid: 6/6;
- provider contract failures/errors: 0;
- observable `protocol_repair` episodes: 0;
- schema lookup caused by grammar repair: 0;
- automatic mutation retry/replay: 0;
- fuzzy/best-match/auto-target: 0;
- latest/rebind/stale substitution: 0;
- direct hidden atomic Browser calls by model: 0;
- runtime task completion judgment: 0;
- undeclared structural-boundary continuation: 0;
- exact ambiguity/not-found remains fail-closed;
- full receipt/evidence remains exactly hydratable from compact refs.

A row that succeeds only after protocol repair does **not** satisfy the cognition-preserving Gate even if the external task oracle passes.

## 7. Efficiency diagnostics

Collect but do not substitute for the hard Gate:

- total model rounds;
- semantic operation calls;
- support calls (`get_tool_schema`, exact evidence hydrate);
- model-visible operation argument/result chars;
- provider input/output tokens;
- cache-hit tokens/rate;
- SRTA;
- one-action vs multi-action horizon distribution;
- duplicate navigation/observation counts;
- internal capture/poll counts separately from model-visible rounds.

The desired trend is lower interface tax without suppressing useful model reasoning.

## 8. Deterministic pre-live tests

Before any live Ornith matrix, add deterministic fixtures that prove:

1. `do:"wait"` canonical call compiles mechanically to the existing typed Predicate path;
2. ordinary boolean conditions can omit mechanical `operator/value` scaffolding when the semantic meaning is unambiguous;
3. one-action horizons work for every canonical operation;
4. multi-action horizons remain optional;
5. no natural action shorthand introduces target inference/fuzzy matching;
6. precise contract errors identify the mechanical mismatch;
7. compact receipts contain enough exact refs for hydration;
8. MF-4 structural-boundary halts remain unchanged.

## 9. Execution order

```text
MF-5.2-A read-only surface audit
  -> MF-5.2-B deterministic RED for cognition-preserving affordances
  -> MF-5.2-C narrow compiler/schema changes only if RED proves a gap
  -> committed-state focused/adjacent/full qualification
  -> zero-model frozen preflight
  -> fresh 6-row treatment qualification
  -> only if hard PASS: MF-6 independent confirmatory
```

Do not jump directly from a nicer schema to live qualification without deterministic proof that authority boundaries are unchanged.

## 10. Stop rules

Stop and redesign instead of expanding automation if any proposed convenience requires the runtime to infer:

- which target the model meant;
- which alternate action should be tried;
- whether a task is complete;
- whether an ambiguous world state is “good enough”;
- whether a failed action should be replayed;
- whether the model should batch more future steps than it has already decided.

The core acceptance criterion remains:

> **The model thinks normally; Semantic Runtime acts precisely.**
