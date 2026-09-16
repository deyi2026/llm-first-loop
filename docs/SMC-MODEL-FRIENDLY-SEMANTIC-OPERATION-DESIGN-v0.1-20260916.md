# SMC Model-Friendly Semantic Operation Design v0.1 — 2026-09-16

Status: **DESIGN AMENDED / MF-5 EVIDENCE INCORPORATED / COGNITION-PRESERVING RULING ACTIVE**

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

### 0.1 Higher-order ruling: Cognition-Preserving Semantic Actuation

The model-facing optimization must obey an even stronger rule:

> **Semantic Manipulation must not require the model to change how it thinks.**

Semantic Operation is the model's **actuation surface**, not its reasoning language. The model continues to understand the task, compare alternatives, form plans, revise beliefs and decide the next action using its native reasoning behavior. Only after the model has decided that a real-world action is needed should Semantic Runtime enter the loop.

Preferred cognitive/execution flow:

```text
understand task
  -> reason normally
  -> decide next action
  -> invoke semantic actuation only if an action is needed
  -> runtime grounds / guards / executes / observes mechanically
  -> return factual delta
  -> reason normally again
```

Forbidden inversion:

```text
learn a Semantic DSL
  -> reshape reasoning around tool grammar
  -> guess schema/protocol fields
  -> repair syntax
  -> only then continue task reasoning
```

The runtime may reduce **execution friction**; it must not introduce a new **cognitive protocol tax**. A shorter JSON wire is not model-friendly if the model must spend reasoning effort remembering special discriminators, schema exceptions, polling mechanics or receipt structure.

This yields two top-level invariants:

> **Do not change how the model thinks.**

> **Only mechanize actions the model has already decided to take.**

These sit above MDEH, SDB, SRTA and Interface Tax. Those concepts are mechanisms for implementing the ruling, not a replacement reasoning framework for the model.

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

The design objective is therefore not “fewer tools at any cost” or “more automation”. It is **lower semantic interaction amplification without expanding program semantic authority and without forcing the model to reorganize its reasoning around an execution DSL**.

A useful distinction is:

- **Cognitive dependency** — requires model understanding/judgment and must remain a model turn;
- **Actuation dependency** — required only to carry an already-decided action into the machine world and should be mechanically compressed;
- **Protocol dependency** — exists only because an API requires bookkeeping; this is pure interface tax and should be eliminated from model reasoning wherever possible.

---

## 2. New first-class concept A: Model-Declared Execution Horizon

### 2.1 Definition

A **Model-Declared Execution Horizon (MDEH)** is the finite ordered set of semantic operations that the model has already decided can be attempted without another model judgment.

MDEH is an **execution handoff description, not a reasoning or planning requirement**. The model never needs to pre-build a multi-step horizon just to be “efficient”. A horizon of one action is valid and often preferable when the model naturally wants to inspect the result before deciding again. Multi-step batching is appropriate only when those later actions are already decided as part of ordinary reasoning.

Example:

```json
{
  "steps": [
    {"do": "navigate", "url": "https://example.invalid/form"},
    {"do": "set_text", "target": {"kind": "input", "name": "Project code"}, "text": "ZX-41"},
    {"do": "wait", "target": {"kind": "button", "name": "Save"}, "until": "enabled", "within_ms": 5000},
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
- **protocol-induced reasoning events**: model turns spent interpreting/guessing/repairing tool grammar rather than advancing task semantics;
- schema-repair loops after a semantically correct intent was already formed;
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

## 6. Input design: natural actuation call, not a model reasoning DSL

The current bounded operation contract is intentionally strict, but it repeats structural fields such as `clauses`, `kind=mutate`, `target.kind=object`, `args`, `mode`, polling interval and other protocol scaffolding.

The goal is **not** to make the model learn a better DSL. The goal is to make the tool call look like the smallest structured expression of an action the model has already decided in ordinary reasoning.

The provider/runtime may expose a short discriminated wire such as:

```json
{"steps":[{"do":"navigate","url":"https://example.invalid"}]}
```

```json
{"steps":[{"do":"set_text","target":{"kind":"input","name":"Project code"},"text":"ZX-41"}]}
```

```json
{"steps":[{"do":"wait","target":{"kind":"button","name":"Run check"},"until":"enabled","within_ms":5000}]}
```

These shapes are execution encodings, not prescribed thought templates. The model should not need to reason in terms of `steps`, discriminators, polling fields or receipt schemas before deciding what it wants to do.

### 6.1 Design requirements

- no natural-language parser in the hard execution path;
- no fuzzy target resolver;
- closed schema;
- structurally discriminated operations;
- exact target semantics remain inspectable;
- role may be optional only if exact uniqueness remains mechanically provable;
- default write semantic should be explicit (`set_text` vs `append_text`) rather than a generic `fill` plus mechanically repetitive `mode` where possible;
- polling interval should be runtime-owned unless user/task semantics explicitly require cadence;
- timeout/deadline stays model-owned only when it encodes task meaning; otherwise a bounded runtime default may be used and surfaced;
- one semantic action concept should have one regular tool-local form; avoid grammar exceptions the model must remember;
- canonical examples may live in the tool-local schema/description, but the universal prompt must not teach a new reasoning procedure;
- contract rejection should tell the model the precise mechanical mismatch, not invite open-ended schema guessing;
- the model must remain free to reason first and call the tool only when it independently decides an action is needed.

### 6.2 Natural use does not mean opaque prose interpretation

“Do not change model thinking” does **not** authorize a vague program-side natural-language planner. A free-form `operate("fill the project code")` interface would reduce characters but could destroy key properties:

- it forces the program to interpret target/action semantics;
- it weakens deterministic qualification;
- it makes provider/model behavior harder to compare;
- it creates hidden semantic routing.

Model-friendly therefore means **natural model decision -> minimal structured actuation -> strict mechanical execution**, not opaque prose automation and not a new thought DSL.

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

## 9. Wait rule: think naturally about the condition; runtime owns polling mechanics

The model chooses the semantic condition because that is part of task reasoning. The runtime performs the bounded sampling because that is execution mechanics.

The model's reasoning may simply be “wait until the Finalize button is enabled”. The tool call should encode that decision directly, without requiring the model to first translate its reasoning into an internal Predicate vocabulary. A provider-facing form may be:

```json
{"do":"wait","target":{"kind":"button","name":"Finalize"},"until":"enabled","within_ms":10000}
```

The runtime may mechanically derive:

- canonical Predicate wire fields from the model-facing condition (for example `until:"enabled"` -> `property=enabled, operator=eq, value=true`);
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
- provider-specific semantic behavior that makes the architecture non-portable;
- teaching the model a mandatory semantic-operation planning/thinking format;
- evaluating success by “how well the model speaks our DSL” instead of whether normal reasoning can naturally invoke qualified actions.

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
- protocol-induced reasoning/schema-repair loops after a correct semantic intent: 0;
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

The project should optimize Semantic Manipulation around these invariants, in priority order:

> **Do not change how the model thinks.**

> **The model spends reasoning/tokens on task semantics, not protocol bookkeeping.**

> **Semantic Operation is actuation: it carries an already-decided model action into the machine world.**

And this safety counterpart:

> **The program may remove mechanical work from the model, but may not remove a semantic decision from the model.**

The immediate next work is **MF-0 Read-only Interface Tax Audit**, not production code modification.


---

## 15. Validation addendum — MF-5 v0.1 (2026-09-16)

The original v0.1 design hypothesis was partially confirmed and partially falsified by formal MF-5 A/B evidence. Compact projection and the short semantic surface materially reduce Interface Tax, but the first short grammar is not yet regular enough for stable model use.

The key falsification is grammatical: the design example used a special top-level `wait` discriminator while ordinary operations used `do`. In measured runs, Ornith repeatedly normalized the language itself and emitted `do:"wait"`; 25/29 B contract failures were therefore `short_operation_not_supported`. This is a design defect in the model-facing language, not a reason to relax exact grounding.

The design rule is strengthened accordingly:

> **A model-facing semantic language should use one regular discriminator for peer operations unless a distinct discriminator encodes a real semantic distinction.**

Wait is a peer semantic step, so the provider-facing grammar should expose one regular action family rather than make the model remember a one-off structural exception. `d6ec0113` implements the concrete `do:"wait"` regularization; the next question is whether even that structured surface stays out of the model's reasoning path and functions only as actuation.

A second lesson is methodological: treatment qualification and baseline comparison are distinct questions. A legacy baseline may remain useful for paired efficiency comparison even when it is not itself release-qualified. Future protocol identities should keep the treatment's hard correctness/safety Gate separate from comparative A/B metrics, without changing the already-frozen MF-5 v0.1 verdict.

See `docs/SMC-BROWSER-MODEL-FRIENDLY-MF5-v0.1-RESULT-20260916.md` for the complete evidence and hashes.

### 15.1 Post-MF-5 cognition-preserving correction

MF-5 exposed a deeper issue than the `wait` discriminator itself. Even after making the grammar shorter, failed trajectories showed the model spending reasoning on statements such as “the wait step needs an operator”, “wait-only operations are rejected”, and repeated attempts to infer how the interface wanted the thought to be encoded. That is **protocol-induced reasoning**.

The correct remediation is not to make the model better at remembering the Semantic Operation language. The interface must instead make a normal model decision map directly onto a qualified actuation call.

Therefore MF-5.1/MF-5.2 work must evaluate two independent properties:

1. **Mechanical regularity** — one consistent tool-local action grammar, no hidden special cases;
2. **Cognitive preservation** — the model can reason in its ordinary task language and only enters the semantic tool contract at the moment of action, without schema-guess/repair becoming part of the task trajectory.

A future qualification should explicitly classify every model turn into `task_reasoning`, `actuation_call`, `protocol_repair`, or `evidence_inspection`. The target is not to suppress task reasoning; it is to drive `protocol_repair` toward zero while preserving or improving task correctness.

This also changes the interpretation of MDEH: an execution horizon is **not a planning format the model must construct in advance**. It is merely the set of actions the model happens to have already decided and chooses to hand off together. A one-action horizon is perfectly valid and should remain the common case when the model naturally wants to inspect the result before deciding again.

---

## 16. Validation addendum — MF-5.2 v0.2: cognition preservation requires perception (2026-09-16)

Formal MF-5.2 v0.2 evidence falsifies the idea that a sufficiently natural **actuation-only** surface is enough. The treatment preserved all mechanical safety boundaries but achieved only 3/6 external task correctness; both delayed-wait repeats failed, and one of them failed with zero observable contract/schema repair.

The dominant remaining contract mismatch is no longer wait syntax. Sixteen of eighteen contract failures came from the model naturally trying to express **page/document observation or readiness** through an object-target wait. Fourteen additional calls were contract-valid but halted `target_not_found`, showing that the model then used exact actuation calls to probe guessed world identities.

This strengthens the architecture law:

> **Perception is a cognitive dependency when the model needs to understand the world; it must not be optimized away as if it were protocol overhead.**

The preferred model-facing loop is therefore:

```text
perceive when understanding is needed
  -> native model reasoning
  -> one already-decided semantic action
  -> runtime actuation + compact mechanical delta
  -> native model reasoning
  -> perceive again only when broader state is needed
```

A second measured correction concerns MDEH. Across 53 semantic-operation calls, 52 recognized calls were single-action and zero were multi-action. Therefore:

> **Single action is the primary cognition-preserving actuation form. MDEH batching is optional and secondary.**

The `steps:[...]` wrapper should be treated as a candidate Interface Tax item for MF-5.3. A direct single-action wire should be audited before further production work.

A third correction is target-domain separation. Scope/page conditions (`ready`, URL/current document state) are not object identities and should not require the model to fabricate `document/page` objects. MF-5.3 must audit a natural scope-wait affordance that mechanically maps to existing scope Predicate primitives without exposing `scope_ref/version` bookkeeping or granting program strategy authority.

Finally, compact receipts remain valuable but are not a replacement for perception. They should carry local mechanical effects; model-visible perception remains available when the next semantic decision genuinely requires broader world state.

See `docs/SMC-BROWSER-COGNITION-PRESERVING-ACTUATION-MF5.2-v0.2-RESULT-20260916.md` for exact evidence and hashes.

---

## 17. MF-5.3 architecture addendum — perception + direct actuation

MF-5.3 read-only audit refines Cognition-Preserving Semantic Actuation into a two-capability model-facing architecture:

> **Perceive is the eye; Operate is the hand. Wait is read-only perception, not actuation.**

> **One already-decided mutation maps to one direct action call. Batching is optional execution compression, not the default thought/call format.**

> **Post-action evidence has three levels: bounded compact delta -> exact hydrate of already-captured evidence -> fresh full snapshot. The model decides semantic sufficiency; the runtime exposes only mechanical comparability/completeness/boundary facts.**

The existing Browser implementation already supplies the mechanical primitives. The design task is to compose them into a smaller cognitive surface without weakening exact grounding, stale/version checks, session fencing, mutation single-dispatch or evidence durability.

See `docs/SMC-BROWSER-MF5.3-READ-ONLY-ARCHITECTURE-AUDIT-20260916.md` for evidence, authority boundaries and the staged next plan.
---

## 18. MF-5.3 deterministic implementation addendum — two capabilities are now real

The MF-5.3 design has now been implemented and deterministically qualified at `d415daa048ce8c96eddefe4fb06b1d996673e0d4`. The important final correction was at Factory/Registry level: having a model-friendly `Perceive` and `Operate` class was insufficient while five typed waits plus low-level action/semantic-execute tools were still normally registered. Final Factory assembly therefore exposes exactly one Browser capability in perception-only mode and exactly two when mutation is enabled: `browser_perceive` and `browser_semantic_operation`. Low-level executors remain implementation mechanics, not normal model concepts.

The provider-facing architecture is now mechanically:

```text
Perceive(snapshot | hydrate | diff | wait)
  -> native model reasoning
  -> Operate(one direct mutation)
  -> compact mechanical delta
  -> native model reasoning
  -> exact hydrate or fresh Perceive only when needed
```

Wait is no longer part of the actuation provider grammar. `steps:[single]` is no longer the normal actuation wire. Compact delta reports only mechanical comparability/completeness/scope/count facts and never task success. Exact old `steps` execution is retained only for historical deterministic evidence compatibility.

At the final committed HEAD the actual two-tool lazy schema is 4,054 chars, SHA256 `b2549e11adb78ca1cd1e7bb252d0ef928e0171fe1cc2c7918706c499f4e24017`. The earlier ~3,560 figure was a design estimate, not a release target.

Deterministic qualification is GREEN; live Ornith qualification remains pending. See `docs/SMC-BROWSER-MF5.3-DETERMINISTIC-IMPLEMENTATION-RESULT-20260916.md`. MF-6 remains deferred.

---

## 19. MF-5.3 measured correction — the architecture works; Perceive must become root-direct

Formal MF-5.3 v0.1 evidence separates architecture from wire format.

The architecture signal is strong: with `browser_perceive` and direct single-action `browser_semantic_operation` both available, all six external tasks passed, including delayed_wait 2/2. There were no target-not-found grounding probes, no duplicate successful mutation, no Operate failure, and no schema lookup.

The treatment still failed its frozen cognition-preserving Gate because `browser_perceive` produced eight contract failures. Six occurred when the model expressed a semantically correct page wait but serialized the nested `condition` object as a JSON string. Two occurred when `hydrate` inherited the snapshot-only `projection_limit` field from the broad top-level parameter surface.

This adds a more precise interface law:

> **A cognition-preserving tool should not require nested protocol objects when the same semantic distinction can be expressed as a closed root branch. Action-specific fields should not coexist in one broad parameter bag.**

The next Perceive provider shape should therefore use root-discriminated closed branches. `action=wait` remains perception, but `kind/page_url/match/url/...` or `kind/object_state/object_ref/...` should be peers in the selected branch rather than nested under a second object. `snapshot`, `hydrate`, and `diff` branches should expose only their own applicable fields.

Do not solve the measured failures with JSON-string coercion or permissive extra-field dropping. Those would make the program guess protocol intent. The better solution is to remove unnecessary protocol structure while preserving fail-closed execution.

A second measured fact is that all 14 compact operation deltas were mechanically incomplete on this fixture set. Navigation changed document generation/scope; same-scope mutations reported unstable object identity. The runtime correctly surfaced those reasons and the model frequently escalated to snapshot/hydrate. This validates the sufficiency boundary but shows that perception bandwidth is still expensive. Optimize identity stability and perception projection only after the Perceive wire hard-passes, so efficiency tuning does not obscure the remaining contract problem.

See `docs/SMC-BROWSER-COGNITION-PRESERVING-MF5.3-v0.1-RESULT-20260916.md` for exact Gate evidence and hashes. MF-6 remains deferred.

---

## 20. MF-5.3.1 deterministic correction — prefer semantic branch regularity over byte minimalism

MF-5.3.1 implements the interface law learned from the 6/6-correct-but-not-qualified MF-5.3 measured run:

> **When action variants have different semantics, expose closed root branches rather than one broad parameter bag plus nested protocol objects.**

Perceive now has root-direct action-specific branches. In particular, natural waits are expressed as:

```text
action=wait + kind=page_url + match + url
```

or:

```text
action=wait + kind=object_state + exact object_ref + state + value
```

rather than requiring a second nested `condition` object.

This does not flatten semantic distinctions away. `kind` remains explicit and every branch is closed. The program still refuses unknown fields/kinds and still performs no fuzzy repair.

The measured evidence also changes how Interface Tax should be interpreted. A root-direct closed `oneOf` can consume more schema bytes because constraints repeat across branches, yet still be cognitively cheaper because the model no longer has to construct an embedded mini-protocol or remember which fields belong to another action.

Therefore optimization priority is:

1. task correctness and authority safety;
2. cognition-preserving semantic regularity;
3. observable protocol-repair reduction;
4. only then serialized prefix size and perception bandwidth.

Do not sacrifice items 1–3 merely to minimize schema bytes.

The next live qualification should test whether the exact repair class from MF-5.3 v0.1 disappears under this root-direct surface. No claim of live improvement is made by the deterministic result alone.
