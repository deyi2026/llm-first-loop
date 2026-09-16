# SMC Model-Friendly Semantic Operation Design v0.1 — 2026-09-16

Status: **DESIGN FREEZE CANDIDATE / NO PRODUCTION IMPLEMENTATION YET**

Baseline: `lfl/main@2c4b9b087f5d2fad2cf2c5c026194038c7613c5c`

Related evidence/design:

- `docs/SMC-CONTRACT-v0.1.md`
- `docs/SMC-BROWSER-V0.6-FCR-INTERFACE-DESIGN-20260913.md`
- `docs/SMC-BROWSER-SEMANTIC-EXECUTE-CONFIRMATORY-v0.5-RESULT-20260913.md`
- `docs/SMC-BROWSER-BOUNDED-SEMANTIC-OPERATION-FC2B-v0.1-RESULT-20260913.md`
- `docs/SMC-BROWSER-BOUNDED-SEMANTIC-OPERATION-FC2C-FCR-v0.2-RESULT-20260913.md`

This document is an additive model-facing design layer. It does **not** rewrite the frozen SMC v0.1 semantic contract and does not weaken its grounding/version/single-dispatch/fail-closed boundaries.

---

## 0. Architecture ruling

The next SMC optimization target is no longer “add more Browser capability”. The mechanical Browser stack is already broad enough to expose a more important bottleneck: **the model pays too much protocol and round-trip tax to use already-qualified mechanics**.

The primary design law is therefore:

> **Only call the model when the next step requires model reasoning.**

Equivalent operational form:

> **Compress mechanical dependency; preserve semantic dependency.**

Equivalent LLM-First boundary:

> The model decides **what to do, to which semantic object, and when it needs to think again**. The Semantic Manipulation Runtime performs only the mechanically derivable observation, exact grounding, version validation, bounded wait, single dispatch, post-observation, diff and evidence persistence needed to carry out that already-declared intent.

This is an efficiency rule and an authority rule at the same time. Reducing round trips is good only when the removed round contained no genuine semantic decision.

---

## 1. Problem statement: the remaining cost is interface friction

The current implementation already proves several important pieces:

- `browser_semantic_execute` lets the model choose only verb + exact grounding ref + semantic args while the program derives action identity/scope/version fields;
- `browser_semantic_operation` can execute 1..8 model-declared ordered clauses;
- each object clause is exact-unique grounded; 0 or >1 matches halt;
- mutation delegates to the qualified single-dispatch/version-guard/ActionReceipt path;
- wait delegates to typed Predicate evaluation;
- no fuzzy match, best match, automatic target choice, latest substitution, rebind, mutation retry/replay or task-completion judgment is allowed.

The remaining friction is mostly model-facing:

1. the model still repeats structural protocol fields that carry little or no task semantics;
2. success paths can return evidence structures far larger than the model needs for the next decision;
3. a model may be asked to explicitly re-observe even when the mutation path has already captured before/after state and produced a diff;
4. common mechanical loops such as wait polling can be internalized without changing model authority;
5. multi-step execution exists, but the boundary for when a batch must stop and return control to the model is not yet a first-class architecture concept.

The design objective is therefore not “fewer tools at any cost” or “more automation”. It is **lower semantic interaction amplification without expanding program semantic authority**.

---

## 2. New first-class concept A: Model-Declared Execution Horizon

### 2.1 Definition

A **Model-Declared Execution Horizon (MDEH)** is the finite ordered set of semantic operations that the model has already decided can be attempted without another model judgment.

Example:

```json
{
  "steps": [
    {"do": "navigate", "url": "https://example.invalid/form"},
    {"do": "set_text", "target": {"kind": "input", "name": "Project code"}, "text": "ZX-41"},
    {"wait": {"target": {"kind": "button", "name": "Save"}, "enabled": true}, "within_ms": 5000},
    {"do": "click", "target": {"kind": "button", "name": "Save"}}
  ]
}
```

The runtime may mechanically execute these declared steps in order. It may not add, delete, reorder, reinterpret or substitute a step.

### 2.2 What the runtime may do inside the horizon

For each declared step the runtime may:

1. capture the current world mechanically;
2. exact-resolve the declared semantic identity;
3. require exact uniqueness when identity lookup is used;
4. derive canonical grounding/scope/version/action-id fields;
5. enforce stale/version/scope preconditions;
6. poll a model-declared Predicate using bounded mechanical timing defaults;
7. single-dispatch an already-declared mutation;
8. capture post-action state;
9. compute mechanical SemanticDiff;
10. append durable ActionReceipt / observation evidence;
11. continue to the next already-declared step only while the execution horizon remains mechanically valid.

### 2.3 What the runtime may not do inside the horizon

It may not:

- invent a new action;
- choose a semantically preferable object;
- fuzzy-match or “best match” a target;
- reinterpret a failed target as a similar target;
- choose a newer snapshot/latest ref as a substitute for the model’s declared object;
- automatically retry/replay a mutation with unknown idempotency;
- decide that a task is complete or successful in the user’s sense;
- decide that an unexpected UI state is “close enough” to continue;
- cross an undeclared structural boundary and keep executing as if the world were unchanged.

---

## 3. New first-class concept B: Semantic Decision Boundary

A **Semantic Decision Boundary (SDB)** is any point where continuing requires interpretation, preference, ambiguity resolution, strategy or task-level judgment rather than a mechanical consequence of the model’s already-declared intent.

When an SDB is reached, the runtime must halt the current execution horizon and return compact evidence to the model.

### 3.1 Mandatory halt conditions

The following are mandatory SDB/halt conditions:

| Condition | Runtime behavior |
|---|---|
| exact target match count = 0 | halt; report not found + observation ref |
| exact target match count > 1 | halt; report ambiguity + exact candidates if mechanically bounded |
| stale/version precondition mismatch | halt; no implicit latest/rebind |
| predicate = unsatisfied at deadline | halt; report unsatisfied evidence |
| predicate = indeterminate | halt; preserve unknown; do not infer false |
| mutation rejected | halt; no automatic alternate action |
| mutation outcome ambiguous | halt; no replay |
| grounding/observation unavailable | halt; report mechanical reason |
| undeclared document/frame/window/dialog/native-boundary transition | halt; return boundary event |
| clause sequence exhausted | return control; `task_completion=not_evaluated` |

### 3.2 Declared vs undeclared transition

A declared `navigate` step is an explicit world transition and may be followed by later model-declared steps, subject to fresh exact grounding in the new world.

An unexpected window/document/dialog transition caused by an ordinary click is different. Even if a later target has an exact textual identity in the new world, continuing could become **cross-world exact rebind**, which is mechanically exact but semantically unauthorized.

Rule:

> **Declared structural transitions may continue. Undeclared structural transitions halt.**

This rule prevents “exact” from becoming a loophole for unintended strategy.

---

## 4. New first-class concept C: Semantic Round-Trip Amplification

### 4.1 Definition

**Semantic Round-Trip Amplification (SRTA)** measures how many model↔tool interaction rounds are required to realize one semantic intent that the model had already fully decided.

A simple first metric is:

```text
SRTA = model-facing tool interaction turns / model semantic decision points
```

The exact denominator must be frozen per evaluation fixture so it does not become a subjective post-hoc score.

The optimization target is not blindly SRTA=1 for every task. The target is:

> **SRTA approaches 1 for purely mechanical continuations, while genuine semantic decision boundaries remain explicit model turns.**

### 4.2 Companion metrics

A qualification should collect at least:

- model tool-call count;
- model-visible tool-result count;
- tool argument serialized chars;
- tool result serialized chars;
- provider input tokens / new prefill tokens where available;
- `get_tool_schema` count;
- explicit `snapshot` count;
- explicit `hydrate` count;
- internal runtime captures (separate from model round trips);
- first valid semantic operation round;
- model-facing contract rejection count;
- wait polling samples (internal, not model rounds);
- full receipt hydrations requested by model;
- task oracle result;
- stale/ambiguous/boundary halt counts;
- automatic retry/rebind/fuzzy counts, which must remain zero.

---

## 5. New first-class concept D: Interface Tax

**Interface Tax** is protocol material the model must emit or consume that is not itself a semantic task decision.

Classify every model-facing field into exactly one of these categories:

### A. Model-semantic required

The model must own these because removing them would transfer a semantic decision to the program.

Examples:

- action verb or high-level operation (`click`, `set_text`, `select`, `navigate`);
- target semantic identity chosen by the model;
- text/value/url selected from user/task intent;
- Predicate property/operator/value;
- ordering of model-declared steps;
- an explicit timeout/deadline only when task semantics require one.

### B. Mechanically derivable

The program should derive these from current canonical observation and the model’s declaration.

Examples:

- schema/domain constants;
- scope ref;
- expected version;
- version scope;
- action id;
- target physical identity;
- `target=scope_ref` relationships;
- fixed atomicity/single-dispatch metadata;
- bounded default polling interval;
- object-vs-resource dispatch mechanics;
- before/after snapshot refs generated during execution.

### C. Evidence-only

These should be persisted durably but not necessarily repeated in every model-facing success result.

Examples:

- full ActionReceipt revision history;
- full before/after grounding bundles;
- full SemanticDiff object lists;
- complete sensor provenance;
- verbose completeness diagnostics when no decision depends on them.

### D. Forbidden inference

These must not be auto-derived because doing so would move semantic authority into the program.

Examples:

- “best” target;
- “probably intended” target;
- relevance/importance ranking;
- task success/completion;
- whether a changed UI satisfies the user’s broader goal;
- whether an alternate action should be attempted after failure.

Every new model-facing field should justify why it is Category A. If it is B or C, default design pressure is to remove it from the normal model call path.

---

## 6. Input design: semantic shorthand without semantic authority transfer

The current bounded operation contract is intentionally strict, but it repeats structural fields such as `clauses`, `kind=mutate`, `target.kind=object`, `args`, `mode`, polling interval and other protocol scaffolding.

The v0.2 design should investigate a shorter discriminated grammar such as:

```json
{"steps":[{"do":"navigate","url":"https://example.invalid"}]}
```

```json
{"steps":[{"do":"set_text","target":{"kind":"input","name":"Project code"},"text":"ZX-41"}]}
```

```json
{"steps":[{"wait":{"target":{"kind":"button","name":"Run check"},"enabled":true},"within_ms":5000}]}
```

This is an example shape, not yet the frozen wire contract.

### 6.1 Design requirements

- no natural-language parser in the hard execution path;
- no fuzzy target resolver;
- closed schema;
- structurally discriminated operations;
- exact target semantics remain inspectable;
- role may be optional only if exact uniqueness remains mechanically provable;
- default write semantic should be explicit (`set_text` vs `append_text`) rather than a generic `fill` plus mechanically repetitive `mode` where possible;
- polling interval should be runtime-owned unless user/task semantics explicitly require cadence;
- timeout/deadline stays model-owned only when it encodes task meaning; otherwise a bounded runtime default may be used and surfaced.

### 6.2 Why not hide everything behind prose

A natural-language `operate("fill the project code")` interface would reduce characters but destroy key properties:

- it forces the program to interpret target/action semantics;
- it weakens deterministic qualification;
- it makes provider/model behavior harder to compare;
- it creates hidden semantic routing.

Model-friendly means **short structured semantics**, not opaque prose automation.

---

## 7. Output design: compact projection + exact hydrate

The full mechanical evidence remains durable. The default model-facing result should be the smallest lossless-enough projection needed to choose the next semantic action.

### 7.1 Normal success projection

Illustrative shape:

```json
{
  "status": "completed",
  "steps_executed": 4,
  "world_version": "...",
  "effects": {"created": 0, "removed": 0, "changed": 3},
  "boundary": null,
  "receipt_ref": "...",
  "diff_ref": "...",
  "task_completion": "not_evaluated"
}
```

### 7.2 Halt projection

Illustrative shape:

```json
{
  "status": "halted",
  "step": 3,
  "reason": "ambiguous_target",
  "match_count": 2,
  "observation_ref": "...",
  "receipt_ref": "...",
  "automatic_retry": false
}
```

If exact bounded candidate cards are useful for model disambiguation they may be included as **mechanical observations**, not ranked recommendations.

### 7.3 Hydration rule

Full receipt/diff/grounding evidence must remain exactly recoverable by stable ref. The runtime may compact the model projection; it may not discard authoritative evidence or replace it with a semantic summary.

This follows the broader LFL pattern:

```text
Durable full evidence
    -> compact mechanical projection
    -> exact on-demand hydration
```

---

## 8. Re-observation rule: do not charge the model twice for the same mechanical fact

If the mutation adapter already performs:

```text
pre-capture -> version guard -> dispatch -> post-capture -> diff -> receipt
```

then a blanket instruction that the model must always call `snapshot` again after every successful mutation creates a duplicate round in cases where the receipt/diff already contains the facts needed for the next decision.

New rule:

> **Do not require a model-visible re-observation when the runtime already produced a fresh grounded post-observation and a mechanically sufficient delta.**

A new model-visible perception call remains appropriate when:

- the model needs broader world context than the compact post-action projection contains;
- diff completeness is insufficient;
- a boundary event changes the interpretation scope;
- the next decision depends on objects outside the returned projection;
- the model explicitly requests inspection.

This removes duplicate observation without granting the runtime any new semantic judgment.

---

## 9. Wait rule: internal polling, external semantic condition

The model chooses the condition. The runtime performs the bounded sampling.

The model should normally declare something like:

```json
{"wait":{"target":{"kind":"button","name":"Finalize"},"enabled":true},"within_ms":10000}
```

The runtime may mechanically derive:

- canonical Predicate wire fields;
- exact target grounding;
- scope;
- sample interval default;
- repeated observations;
- final tri-state Predicate result.

It must preserve:

- `satisfied`;
- `unsatisfied`;
- `indeterminate`.

It must not convert unknown/partial observation into false certainty.

---

## 10. Tool-surface convergence

Long term, the model-facing Browser surface should tend toward two conceptual operations:

1. **Perceive / understand unknown world**
2. **Operate on already-understood semantics**

Existing lower-level tools may remain as internal execution primitives, debugging/qualification surfaces or escape hatches. The objective is not to delete useful mechanics but to avoid forcing the model to manually orchestrate them when no semantic judgment is gained.

This implies a preferred flow:

```text
perceive
  -> model semantic decision
  -> operate(MDEH)
  -> compact receipt/diff
  -> model semantic decision only if needed
```

rather than:

```text
snapshot -> schema -> hydrate -> action -> snapshot -> wait -> snapshot -> hydrate -> action -> ...
```

---

## 11. Explicit anti-goals

The following are not acceptable ways to reduce round trips:

- automatic target selection;
- fuzzy/best-match target repair;
- automatic mutation retry/replay;
- hidden latest/snapshot substitution;
- automatic rebind after stale version;
- program task-completion judgment;
- semantic “importance” summarization inside the hard path;
- increasing max rounds to mask interface friction;
- adding large universal prompt instructions instead of fixing local contracts;
- silently crossing an undeclared browser/document/native boundary;
- provider-specific semantic behavior that makes the architecture non-portable.

---

## 12. Qualification strategy

### 12.1 A/B isolation

Freeze the mechanical backend and compare:

- **A**: current FC2-C model-facing wire + current result projection;
- **B**: model-friendly grammar + compact model projection.

Keep identical:

- Ornith model/runtime;
- user prompts;
- Browser fixtures;
- external oracle;
- max rounds;
- grounding semantics;
- version guard;
- single-dispatch semantics;
- Predicate semantics;
- retry/rebind policy;
- actuator and capture backend.

### 12.2 Hard safety/authority gates

B must not regress:

- external task correctness;
- exact target handling;
- stale/version rejection;
- single dispatch;
- unknown/ambiguous outcome honesty;
- no fuzzy match;
- no auto-target;
- no auto-rebind/latest;
- no mutation auto-retry;
- `task_completion=not_evaluated` at runtime layer;
- undeclared structural transition halt.

### 12.3 Efficiency gates

Pre-register improvement targets before live testing. Initial candidate gates:

- First-call-valid: 6/6;
- task oracle: 6/6 in qualification and 6/6 in independent confirmatory repeat;
- model-facing contract rejection: 0;
- `get_tool_schema`: 0 unless an intentionally novel tool is introduced;
- explicit duplicate post-mutation snapshot: 0 when compact receipt/diff is sufficient;
- tool-argument chars: materially lower than A;
- tool-result chars: materially lower than A;
- model-facing round trips: materially lower than A;
- cache/prefix behavior: no material regression;
- internal capture count is recorded separately and is **not** mislabeled as model round-trip cost.

A numeric “materially lower” threshold should be frozen only after the read-only baseline audit has measured the current distribution. Do not invent the threshold post-hoc.

---

## 13. Execution plan

### MF-0 — Read-only Interface Tax Audit

No production edits.

Deliverables:

- field-by-field classification A/B/C/D for current `browser_semantic_operation` input;
- output receipt field classification;
- current FC2-C serialized argument sizes;
- existing model-visible re-observation instructions and actual backend post-capture behavior;
- current explicit snapshot/hydrate/schema round-trip counts from available eval traces;
- candidate minimal grammar, still design-only;
- baseline SRTA definition for the frozen 3×2 fixture.

Exit: audit reviewed; no semantic-authority leak identified in proposed removals.

### MF-1 — Deterministic contract RED tests

Before production implementation, lock:

- shorter model-facing grammar;
- exact-unique target rule;
- no fuzzy/auto-target/rebind/latest;
- declared-transition continue vs undeclared-transition halt;
- compact result projection has exact full evidence refs;
- full receipt remains recoverable;
- no program task completion;
- no duplicate mutation replay.

Exit: deterministic RED demonstrates the intended delta and only the intended delta.

### MF-2 — Narrow input compiler

Implement only mechanical compilation from short model-semantic wire to the existing qualified operation primitives.

Do not change actuator, ActionReceipt semantics or Predicate evaluation.

Exit: focused + adjacent deterministic tests green.

### MF-3 — Compact result projection

Keep full durable evidence. Add model-facing compact projection and exact hydration refs.

Exit: round-trip/output-size tests green; evidence integrity unchanged.

### MF-4 — Execution Horizon / Decision Boundary enforcement

Make structural boundary halts explicit and deterministic. Continue only across transitions that were explicitly declared by the model.

Exit: adversarial tests for ambiguous targets, stale versions, unexpected document/window/dialog transitions and ambiguous dispatch all halt fail-closed.

### MF-5 — Local A/B qualification

Same frozen 3 tasks × 2 repeats, same Ornith/runtime, no increased rounds, no replay.

Collect correctness + SRTA + chars/tokens/rounds + safety gates.

Exit: pre-registered gate PASS.

### MF-6 — Independent confirmatory repeat

Fresh sessions/profile/state, no evidence pooling with MF-5.

Exit: same gate PASS again before calling the interface stable.

### MF-7 — Portability / wider matrix

Only after local repeat stability:

- provider portability;
- broader Browser task matrix;
- later Vision phase;
- OS adapter remains later still.

---

## 14. Decision summary

The project should optimize Semantic Manipulation around this invariant:

> **The model spends tokens on semantics, not protocol bookkeeping.**

And this safety counterpart:

> **The program may remove mechanical work from the model, but may not remove a semantic decision from the model.**

The immediate next work is **MF-0 Read-only Interface Tax Audit**, not production code modification.
