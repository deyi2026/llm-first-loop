# SMC Semantic Logic P2 Core Rule Engine v0.1 — Design Freeze

> Status: **P2 design / docs-only / shadow-only**
> Frozen parent: `54f1ed8c6c0b4cf71ca4b2bd39970df31d2e2ed5` (P1-D PASS)
> RulePack: `smc.browser.p2-core.v0.1`
> RulePack SHA256: `bba3a38c315078e390d1afd985572c962bfcecf076ef9ff623abcdf34ace458b`
> Production consumer: **none**

## 1. Ruling

P2 implements a **closed Typed-IR Core Rule Engine**, not an arbitrary N3/DSL runtime.
The engine may derive deterministic semantic closure only after the model/caller and
Adapter/Runtime have supplied the selected semantic request plus mechanical facts.

P2 MUST NOT:

- choose a target/property/verb/strategy;
- decide Perceive vs Operate;
- recapture, hydrate, refetch or silently rebind physical state;
- reserve an action id, acquire permission/locks, dispatch effects, retry effects, or append receipts;
- infer task/goal completion;
- dynamically load model-authored rules;
- execute arbitrary N3, Python, shell, JavaScript or remote code.

The four-way authority split from P0 remains unchanged: LLM semantic choice; Semantic
Logic deterministic closure; Adapter physical observation/grounding/actuation; Runtime
permission/effect authority and durable mechanics.

## 2. Why P1 FactGraph is not enough by itself

P1's `smc.typed_fact_graph.v0.1` is a lossless **representation** of a canonical output.
Using those already-derived output leaves as both P2 input and expected answer would be
a common-mode false green.

P2 therefore evaluates the P0 `smc.semantic_fact.v0.1` rule-plane shape with an explicit
split:

```text
asserted input facts
  = model-selected facts + Adapter-observed facts + Runtime-authority facts

derived facts
  = mechanically_derived only, each carrying rule + input-fact provenance
```

Qualification fixtures MUST build asserted inputs independently from expected Python
oracle outputs. In particular, `observation.target_present=false` means only “this exact
target id is not in the captured set”; it does not mean world absence. Only the Predicate
rule may combine that explicit membership fact with complete relevant coverage and stable
identity to derive `exists=false`.

## 3. Engine profile

The engine profile is frozen in `SMC-SEMANTIC-LOGIC-P2-RULEPACK-v0.1.json`:

```text
mode                         shadow_qualification_only
evaluation                   one topological pass
dynamic rule loading          disabled
arbitrary code execution      disabled
recursion                     disabled
rule dependency cycles        reject
unknown dependencies          reject
rule firing                   once per exact context
input mutation                forbidden
negation-as-failure           forbidden
missing fact => false         forbidden
runtime authority minting     forbidden
task completion authority     forbidden
```

The evaluator dispatches only the 13 closed `evaluator_op` names in the frozen RulePack.
An unknown op is a pack error, not an extension point.

## 4. Bounds

| Bound | Value |
|---|---:|
| `max_rules` | 64 |
| `max_asserted_facts` | 4096 |
| `max_derived_facts` | 4096 |
| `max_derivations` | 4096 |
| `max_contexts` | 256 |
| `max_rule_dependencies` | 16 |
| `max_scope_nodes` | 1024 |
| `max_scope_depth` | 32 |
| `max_output_facts_per_rule_context` | 64 |
| `max_input_fact_refs_per_derivation` | 64 |
| `max_engine_wall_ms_qualification` | 5000 |
| `rule_firings_per_context` | 1 |

Any pack/input/result that exceeds a bound is rejected as a whole qualification result.
No partial derived set may be treated as qualified after a cap or evaluator fault.

## 5. Hash and identity contract

Each Rule is canonical-JSON hashed with its `rule_hash` field absent. The RulePack is
canonical-JSON hashed with only `rulepack_hash` absent; individual `rule_hash` values are
included. Canonical JSON is UTF-8, sorted keys, compact separators, finite numbers only.

The implementation must validate every rule hash and the RulePack hash before any
semantic evaluation. Derived fact and DerivationRecord ids are deterministic hashes of
rule ref/hash, exact input fact refs, context refs, predicate/value/truth-state, and
output refs. Same pack + same ordered-independent input set must yield byte-identical
canonical output.

## 6. Rule groups

| Group | Rules | Authority |
|---|---:|---|
| G1 Grounding | 2 | mechanical derivation |
| G2 Scope | 2 | mechanical derivation |
| G3 Completeness / Conflict | 4 | mechanical derivation |
| G4 Predicate | 2 | mechanical derivation |
| G5 Version / Receipt | 3 | version is shadow execution-precondition fact; receipt rules mechanical |

### G1 — Grounding

`browser.grounding.exact-binding` consumes an already-observed/hydrated grounding fact.
It never calls a store. Available exact object/resource projections may yield exact
`target_id/scope_ref/observed_version/version_scope`; unauthorized, expired, wrong-kind,
tampered or incomplete facts remain unbound/indeterminate.

`browser.action.fixed-contract` compiles fixed action fields **only after the model has
already selected verb/target_ref/args**. It must not choose or repair those semantic
inputs.

### G2 — Scope

`core.scope.descendant-closure` computes positive ancestry from explicit parent links.
The scope graph is bounded and cycle-checked before evaluation. It never infers negative
membership from missing nodes.

`core.scope.target-relation` returns exact match/mismatch only when both scope facts are
known; otherwise it is indeterminate.

### G3 — Completeness / Conflict

`core.conflict.canonicalize-unresolved` preserves source-qualified disagreements and
emits canonical null/conflict/unresolved when no deterministic resolver contract exists.
Source order cannot create priority.

`core.coverage.derive-status` may claim complete only when the Browser domain's expected
sensor set is explicitly declared and all required coverage facts support completeness.

`core.completeness.separate-observation-projection` makes it impossible for projection
completeness to repair or upgrade physical observation completeness.

`core.identity.ambiguity-no-fusion` consumes Adapter-provided mapping ambiguity; it does
not perform physical matching. Ambiguity yields unresolved/no-fusion.

### G4 — Predicate

The model continues to choose property/operator/value and whether the condition matters.
`browser.predicate.bind-selected-condition` derives only fixed schema/domain/target/scope
fields. `browser.predicate.evaluate` mirrors the frozen closed Browser vocabulary.

P2 v0.1 uses **no negation-as-failure**. For negative existence, the input contains an
explicit capture-membership fact (`observation.target_present=false`). World-level
`exists=false` is derivable only when exact stable identity and complete relevant
coverage are also asserted. Under incomplete coverage the result is indeterminate.
Partial `object_count` is a lower bound: monotonic `ge` success and already-exceeded
`le/eq` failure may be decisive; otherwise result is indeterminate.

### G5 — Version / Receipt

`core.version.assess-precondition` compares only explicit persisted version facts. It
cannot refresh or rebind. Its output remains `execution_precondition_fact` and is
**shadow-only throughout P2**.

Receipt rules consume Runtime-produced receipt/reservation/dispatch facts. They validate
monotonic append-only history, one-dispatch invariants, and no-auto-retry observations;
they do not reserve, dispatch, append, or change receipt status. `receipt.status=ok`
never implies task completion.

## 7. Proof / provenance

Every derived SemanticFact must use `provenance.kind=mechanically_derived` and retain:

```text
rule_ref
rule_hash
derivation_ref
input_fact_refs
exact context refs
```

Every DerivationRecord is inspectable without hidden model reasoning. Runtime-authority
facts may be consumed as premises but Semantic Logic may never emit a fact whose
provenance kind is `runtime_authority`.

## 8. Open-world and fail-closed semantics

Fail-closed is scoped to the claimed mechanical conclusion:

- missing grounding facts => exact binding unproven;
- incomplete coverage => negative absence unproven;
- missing/unstable identity => continuity unproven;
- expired/unavailable version => precondition indeterminate;
- pack/hash/dependency/bounds error => entire engine result rejected.

None of these may be inflated into “no useful action exists”, “the target is irrelevant”,
or “the user cannot complete the task”.

## 9. N3 shadow plane

Typed IR is the P2 engine candidate. N3 remains an **independent qualification plane**.
P2 must not open an arbitrary external rule surface. Each closed `evaluator_op` may have
one tracked, hash-pinned qualification template/query owned by the harness. The harness
may feed only fixture facts and frozen templates to the already-restricted EYE sandbox.
Model/user-provided N3 and remote imports remain forbidden.

P2 v0.1 keeps negation-as-failure disabled. Independent N3 sentinels must specifically
cover S2 conflict, S3 open-world absence/lower-bound, S4 generation pressure, S5 receipt
single-dispatch/no-retry, and forbidden authority outputs. A Typed/N3 agreement that
contradicts the Python oracle is still RED.

## 10. RED-first contract

`SMC-SEMANTIC-LOGIC-P2-RED-GATES-v0.1.json` freezes 64 deterministic gates before
implementation. It includes semantic-oracle gates and engine/authority/bounds attacks.
Important attacks include:

- already-derived output smuggled in as asserted input;
- unknown/missing fact collapsed to false;
- source priority or identity fuzzy fusion;
- silent physical recapture/rebind;
- scope cycles/depth overflow;
- rule cycles/unknown dependency/hash drift;
- forbidden authority class/output;
- dynamic evaluator op;
- Runtime authority minted by a derived fact;
- cap/evaluator fault leaking a partially qualified result;
- receipt `ok` -> task completion;
- transport ambiguity -> automatic retry.

All applicable gates must be RED against the absent P2 engine before production code is
written, and all must be GREEN before P2 can close.

## 11. Qualification plan

Implementation, after this design checkpoint is separately approved:

1. add closed Typed RuleFact/RulePack/Derivation types under `semantic_logic`;
2. add pack/hash/DAG/bounds validator;
3. make every frozen RED fail for the intended reason;
4. implement the 13 fixed evaluator ops group-by-group G1→G5;
5. for each group compare Python oracle vs Typed evaluator vs restricted N3 shadow;
6. run all 64 RED gates as GREEN plus P1 215-case adjacency;
7. run Ruff/Pyright/py_compile/diff/security/full `ci_gate` from committed state;
8. freeze machine/MD P2 result.

No provider-visible schema, Browser tool wiring, Runtime consumer, mutation cutover,
deployment, restart, or local-model change is in P2.

## 12. Promotion boundary

P2 PASS would mean only: **the Core Rule Engine can reproduce frozen deterministic
semantic closure in shadow qualification.** It would not make any rule
`authority_eligible` or `active`, and it would not justify production cutover. A later
selective-authority phase requires fresh corpus/adversarial qualification, mechanical
rollback, and explicit owner authorization.
