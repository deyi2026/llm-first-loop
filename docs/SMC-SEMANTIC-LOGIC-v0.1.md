# SMC Semantic Logic v0.1

> Status: **P0 specification / docs+schema only**
> Frozen baseline: `main@19e253edfe4d3fcbeb268830b90d00fd273a6262`
> Production authority: **none**
> Provider-visible surface change: **none**
> Mutation authority change: **none**

## 1. Purpose

SMC already defines typed semantic objects and execution receipts. P0 adds the missing specification for a future **Semantic Logic Layer** that can derive mechanical relations between those objects without taking semantic agency away from the model.

The target architecture is:

```text
LLM semantic choice
        |
        v
SMC model-facing contract
        |
        v
Semantic Logic Layer
        |
        v
Domain adapter
        |
        v
Physical world
```

The layer is N3-inspired in the sense that it treats source-qualified facts, explicit contexts, rules and derivations as first-class. P0 does **not** require an N3 runtime and does not change existing SMC JSON wire contracts.

## 2. P0 scope

P0 freezes:

- the mechanical rule taxonomy already present in production Python;
- the authority boundary between model, semantic logic, adapter and runtime;
- an N3-compatible internal Fact / Rule / Derivation shape;
- five deterministic shadow gates and their frozen oracle sources;
- adversarial conditions that a future rule engine must preserve;
- the shadow-only boundary for P1-P3.

P0 explicitly does not:

- implement a reasoner;
- change Browser/SMX/FileService production code;
- add or remove provider-visible tools or parameters;
- change routing or Perceive/Operate selection;
- change mutation admission, permission, retry, idempotency or receipt status;
- reduce model-facing fields yet;
- start P1.

## 3. Existing semantic invariants audited at the frozen baseline

### 3.1 Grounding and context identity

Current Browser GroundingRef behavior already enforces:

1. exact reference parsing;
2. session fencing;
3. observation/version binding;
4. retention/expiry visibility;
5. integrity verification;
6. exact hydration of the original canonical projection;
7. no silent refresh, nearest-match replacement or rebind.

For object GroundingRefs, the canonical projection contains a `SemanticObject` with:

```text
id
scope_ref
grounding_ref
observed_version
```

For Browser resource grounding, the projection contains:

```text
kind=page
scope_ref
grounding_ref
observed_version
```

These relations are mechanical and are candidates for common semantic closure.

### 3.2 Scope and generation identity

Browser identity is bound to runtime/page/document/frame generation and stable physical identity, not name similarity.

Frozen consequences:

- reorder of one stable physical object preserves Semantic ID;
- replacement with the same name does not preserve ID;
- same-name duplicates do not force identity fusion;
- page/document/frame generation transitions can invalidate prior identity;
- adapter runtime generation participates in namespace separation;
- snapshot-local AX identities are explicitly unstable.

The semantic logic layer may derive consequences from these facts. It may not invent physical identity.

### 3.3 Source-qualified multi-sensor truth

Current Browser C28 behavior provides the first canonical multi-source rule:

```text
DOM says field = A
AX  says field = B
A != B
and there is no frozen deterministic resolver

=> canonical field = null
=> conflict.resolution = unresolved
=> keep source/value/grounding_ref for both observations
```

Likewise, ambiguous DOM↔AX identity mapping does not force a merged object.

This rule is domain-specific in its sensors but SMC-core in its epistemic shape.

### 3.4 Observation completeness and projection completeness

The audited code already distinguishes two dimensions:

```text
observation completeness
!=
model-facing projection completeness
```

Examples:

- `projection_limit=1` can produce an incomplete model projection while the captured Browser observation remains complete;
- DOM truncation, cross-origin frames or blind spots lower observation completeness;
- hydration can restore omitted projected data but cannot repair a physical observation gap.

This distinction is SMC-core.

### 3.5 Open-world negative discipline

Current Predicate rules implement:

```text
not observed != false
```

Important frozen cases:

- previously stable target absent under complete coverage -> absence may be asserted;
- same target absent under partial coverage -> `indeterminate`;
- invented/unknown identity absent -> `indeterminate`;
- snapshot-local unstable identity absent -> `indeterminate`;
- unobserved property -> `indeterminate`;
- unobserved scope -> `indeterminate`.

### 3.6 Lower-bound reasoning

Incomplete observation can still carry decisive positive witnesses.

For `object_count`, current Python already implements:

```text
observed_count >= requested minimum
=> satisfied even when coverage is incomplete
```

while a non-decisive upper/equality claim remains `indeterminate`.

This is a mechanical monotonic/lower-bound rule, not semantic estimation.

### 3.7 SemanticDiff comparability

Current Browser SemanticDiff compares two explicit persisted observation contexts.

Comparability requires compatible:

- domain;
- semantic scope/document lineage;
- frame document lineage;
- sensor contract.

Frozen consequences:

- same stable object and same comparable scope can produce field-level change;
- full navigation/document generation change is incomparable rather than mass create/remove;
- frame generation change is incomparable for affected child scope;
- sensor-contract change is incomparable;
- incomplete observation suppresses exhaustive created/removed claims;
- snapshot-local unstable identities are excluded from world-level create/remove churn.

### 3.8 Closed Predicate contract

Current Browser Predicate is a closed typed vocabulary:

```text
schema
domain
scope_ref
target
property
operator
value
```

Important relations:

- scope Predicate: `target == scope_ref`;
- object Predicate: target is exact Browser Semantic ID;
- property selects a closed operator/value-type contract;
- evaluation result is `satisfied | unsatisfied | indeterminate`;
- Predicate evaluation does not choose a target, capture a new world, retry an action or judge task completion.

### 3.9 Version/staleness semantics

Current version assessment is an explicit relation between:

```text
expected_version
observed_version
version_scope
scope_ref
target_id?
```

It never refreshes or rebinds automatically.

Frozen outcomes include:

```text
match
stale
indeterminate
```

Examples:

- exact same observation -> `match/exact_version`;
- same object unchanged in a newer observation -> `match/object_unchanged_new_observation`;
- same object changed -> `stale/object_changed_same_generation`;
- document generation changed -> `stale/document_generation_changed`;
- target missing under incomplete current observation -> `indeterminate/target_not_observed_incomplete`;
- expired/unavailable/unauthorized expected observation -> `indeterminate`.

### 3.10 Semantic compilation

Current `browser_semantic_execute` already demonstrates the desired LLM-First split.

Model owns:

```text
verb
exact target_ref
semantic args
```

Compiler derives:

```text
schema
domain
scope_ref
target_id
expected_version
version_scope
action_id
operation_class
idempotency_class
atomicity_class
version_precondition
```

Object refs derive `version_scope=object`; page resource refs derive `version_scope=resource`.

The exact semantic request deterministically derives `action_id`, allowing Runtime reservation to reject exact duplicate dispatch.

### 3.11 Mutation hard boundary

Current Browser mutation path owns:

1. closed verb/args contract;
2. verb-specific version-scope contract;
3. action-id reservation;
4. fresh pre-dispatch observation;
5. explicit version assessment;
6. exact target/scope continuity;
7. stable physical target resolution;
8. current Runtime effect authority;
9. one physical dispatch;
10. no hidden automatic mutation retry;
11. post-dispatch observation and diff attempt;
12. append-only receipt revisions.

Only the pure semantic relations in this chain are candidates for the Logic Layer. Locks, reservation, authority, physical dispatch and durability remain Runtime/Adapter-owned.

### 3.12 ActionReceipt semantics

Current receipt semantics freeze:

- session fencing;
- immutable JSONL revisions;
- monotonically increasing `receipt_seq`;
- `running -> terminal` as separate records;
- same action_id cannot physically dispatch twice;
- transport ambiguity does not trigger automatic replay;
- observed partial effects may still be reported provisionally;
- sensitive semantic args need not be stored in plaintext;
- receipt `status=ok` is not task completion.

## 4. Cross-domain audit

P0 found enough non-Browser evidence to justify a core semantic layer.

### 4.1 SMX / shell projection

`smx_perceive.py` already independently expresses:

- scope identity/relation;
- observation completeness;
- projection completeness;
- snapshot-pair net diff semantics;
- Predicate facts;
- wait ActionReceipt projection;
- grounding of raw receipt evidence.

Therefore scope/completeness/context/diff/provenance are not Browser-only concepts.

### 4.2 FileService

`workspace/file_service.py` already independently expresses:

- immutable `snapshot_ref`;
- exact-byte identity;
- workspace/path scoping;
- version precondition;
- stale content -> `VersionConflict`;
- stable path lock;
- effect mutation authority;
- exact post-write verification;
- explicit non-ownership of task semantics.

This is a second strong precedent for separating semantic/version facts from Runtime hard boundaries.

## 5. P0 rule taxonomy

### 5.1 SMC Core invariants

These are candidates to become cross-domain RulePack concepts:

| Core invariant | Meaning |
|---|---|
| `context_bound_fact` | a fact is bound to explicit scope/version context |
| `source_qualified_fact` | source disagreement is preserved, not silently flattened |
| `grounding_exactness` | exact ref hydration never becomes nearest-match rebind |
| `observation_vs_projection` | capture completeness and display completeness are independent |
| `unknown_not_false` | lack of evidence is not mechanical negation |
| `lower_bound_witness` | incomplete coverage may still support monotonic positive claims |
| `comparability_required` | cross-version difference claims require comparable contexts |
| `identity_not_similarity` | semantic identity is not derived from name/text similarity |
| `version_precondition` | mutation-relevant state is checked against explicit expected state |
| `append_only_revision` | durable status evolution adds revisions instead of overwriting cited truth |
| `proof_provenance` | derived facts preserve rule and input fact identity |

### 5.2 Browser-specific invariants

Remain domain RulePack or Adapter facts:

- DOM/AX sensor vocabulary;
- page/document/frame hierarchy;
- Browser SemanticObject kind vocabulary;
- Browser-specific properties/operators;
- click/fill/select/navigate/scroll verb contracts;
- Browser resource grounding kind `page`;
- CDP physical target representation;
- Browser boundary-event detectors.

### 5.3 Model-owned semantics

Never become mechanical rules:

- choose object/scope of interest;
- choose property/operator/value;
- choose whether to wait;
- choose mutation verb and semantic args;
- choose strategy/recovery;
- judge relevance, importance, success or task completion.

### 5.4 Runtime-owned authority

Never minted by Semantic Logic:

- permissions/authentication;
- session/run ownership;
- current mutation authority;
- resource admission;
- action-id reservation;
- path/process locks;
- fsync/durable append;
- physical dispatch;
- atomic file replace.

## 6. Duplicate implementation audit

P0 identifies duplicated mechanical relationships that justify a future common logic layer.

### D1. Exact object-ref hydration

Equivalent checks appear in multiple Browser call paths:

- `browser_wait.py::_hydrate_object_identity`;
- `BrowserWaitObjectTool._compile_predicate`;
- narrow typed object wait paths;
- `BrowserSemanticExecuteTool.compile_request`.

Common relation:

```text
exact object GroundingRef
  -> available exact canonical projection
  -> semantic object id
  -> scope_ref
  -> observed_version
```

P0 ruling: candidate for one future `SemanticRefResolver`/RulePack relation; no production refactor yet.

### D2. Predicate fixed fields

`schema/domain/scope_ref/target` are assembled and revalidated in multiple typed wait paths.

P0 ruling: model should continue choosing semantic condition; fixed identity fields are mechanical closure candidates.

### D3. Verb/action fixed contract

Verb->args/version-scope/fixed action metadata currently appears in:

- Browser mutation contract;
- semantic compiler;
- provider schema descriptions;
- compact registry guidance;
- frozen profile/schema.

P0 ruling: future canonical RulePack may become the single machine source for derivable action facts, but provider descriptions remain generated/qualified artifacts rather than semantic authority.

### D4. Completeness and diff rules

Browser and SMX independently implement parallel completeness/scope/diff rules.

P0 ruling: lift the abstract epistemic pattern to SMC Core; keep physical sensor meaning in the domain adapter.

### D5. Version-precondition pattern

Browser expected-version checks and FileService expected-snapshot checks are physically different but semantically homologous:

```text
explicit immutable baseline
+ current observation
=> match | conflict/stale | unknown/invalid
```

P0 ruling: share the abstract rule vocabulary; do not force one physical version token format across domains.

## 7. N3-compatible internal semantics

P1 may choose a typed internal IR that can serialize to N3-like statements.

P0 requires that representation to preserve at least:

```text
Fact
Context
Provenance
Rule
DerivationRecord
```

A triple alone is insufficient because SMC facts require source, scope, version, completeness and provenance.

Conceptual example:

```text
context snapshot_101 {
  source dom {
    button enabled true
  }
  source ax {
    button enabled false
  }
}
```

Derived canonical fact:

```text
button enabled unknown
truth_state conflict
derived_by C28-unresolved-conflict
inputs [dom_fact, ax_fact]
```

## 8. Rule shape

Every future executable rule must be closed and versioned.

Minimum fields are defined by `SMC-SEMANTIC-LOGIC-P0-SCHEMA-v0.1.json` and include:

```text
rule_id
rule_version
rulepack_id
domain
authority_class
input_predicates
output_predicates
closed_world_requirements
status
source_refs
fixture_refs
rule_hash
```

No rule may gain authority merely because its textual serialization is valid N3.

## 9. Derivation shape

A mechanically derived result must be inspectable without hidden model reasoning.

```text
DerivationRecord
  derivation_id
  rule_ref
  input_fact_refs
  output_fact_refs
  context_refs
  result
  reason
```

This yields a mechanical proof chain:

```text
derived fact
  -> derivation
  -> rule version/hash
  -> grounded/runtime input facts
  -> immutable observations/receipts
```

## 10. Five frozen Shadow Gates

P0 freezes five initial equivalence gates. The machine manifest is `SMC-SEMANTIC-LOGIC-P0-FROZEN-FIXTURES-v0.1.json`.

### S1 — Grounding Closure

Given an exact object/resource GroundingRef, a future shadow engine must derive the same object/scope/version/action fixed facts as current Python.

Must also preserve fail-closed cases:

- cross-session ref;
- object ref used as resource ref;
- resource ref used as object ref;
- unavailable/expired/tampered ref.

### S2 — C28 Source Conflict

Given Browser `conflict` fixture:

```text
DOM enabled=true
AX enabled=false
```

must derive exactly:

```text
canonical enabled=null
conflict resolution=unresolved
both source/value/grounding refs retained
```

No source priority is allowed.

### S3 — Predicate Honesty

Given a previously grounded stable target that is absent:

- complete relevant coverage -> `exists=false` can satisfy the negative Predicate;
- partial/truncated coverage -> `indeterminate`;
- unknown/unstable identity -> `indeterminate`.

Lower-bound positive cases must remain decidable when mechanically sufficient.

### S4 — Version/Stale

Frozen cases include:

- same object changed in same generation -> stale;
- same object unchanged in newer observation -> match;
- document generation change -> stale + incomparable lineage;
- target absent under incomplete observation -> indeterminate;
- expired/unavailable expected version -> indeterminate;
- no automatic refresh/rebind.

### S5 — Receipt Monotonicity

Frozen execution trace:

```text
first exact action:
  receipt_seq 1 running
  receipt_seq 2 terminal

same exact action repeated:
  receipt_seq 3 rejected duplicate_action_id
  physical dispatch count remains 1
```

Transport ambiguity remains no-retry and can carry provisional observed effects.

## 11. Shadow comparison contract

P1-P3 shadow execution must compare a candidate logic result to current canonical Python without affecting production output.

Minimum ShadowResult:

```text
fixture_id
gate_id
baseline_ref
oracle_result_hash
shadow_result_hash
equivalent
mismatch_paths
derivation_refs
```

Requirements:

- no provider-visible mutation;
- no hidden world recapture solely for shadow comparison;
- no routing/tool selection impact;
- no dispatch/retry/admission impact;
- deterministic serialization for comparable results;
- mismatch is RED, never silently normalized away.

## 12. P0 adversarial paper review

The specification is considered sufficient for P0 only if the following attacks are closed at the contract level.

| Adversary | Required P0 behavior |
|---|---|
| closed-world leak: absent item treated false | require sufficient coverage or return unknown/indeterminate |
| source-priority leak | preserve conflict; no unqualified canonical source selection |
| stale ref rehydrated as current | exact version-bound hydration; unavailable/expired stays factual |
| name-similarity rebind | identity basis/generation required; no fuzzy substitution |
| cross-version fact mixing | contexts remain explicit; derivation inputs name exact contexts |
| projection cap mistaken for sensor blindness | observation/projection completeness remain separate |
| sensor blindness repaired by hydrate | forbidden; hydration cannot improve original observation completeness |
| model-written rule self-authorizes | model rules remain `candidate_only` |
| rule output escalates to permission | Runtime authority is separate and non-mintable |
| rule recursion/unbounded closure | future engine must enforce bounded closed RulePack; P1/P2 gate |
| receipt `ok` interpreted task completion | forbidden authority/output class |
| transport ambiguity auto-replayed | Runtime keeps no-auto-retry invariant |
| raw provenance leaks secrets | privacy-safe grounding/provenance allowed; completeness reports gaps |
| Browser rule falsely generalized to FS | abstract core relation separated from domain-specific physical semantics |

P0 ruling: the contract closes these categories on paper. Runtime/engine enforcement remains unimplemented and therefore unclaimed.

## 13. Qualification boundary

P0 may be declared **PASS** when all are true:

1. exact audit baseline frozen;
2. audited deterministic canonical suite is green;
3. rule taxonomy and authority boundary are documented;
4. machine-readable closed schema exists and parses;
5. five frozen fixture gates reference existing deterministic oracles;
6. adversarial paper review has no unresolved contract-level authority gap;
7. repository changes are docs/schema/fixture-manifest only;
8. no production/provider surface/runtime state changed.

P0 PASS does **not** mean:

- N3 reasoner qualified;
- Semantic Logic implementation exists;
- model success improved;
- production authority changed;
- P1 has started.

## 14. Next-phase decision boundary

Only after P0 is frozen should P1 compare:

```text
P1-A: native typed Semantic Rule IR
P1-B: direct N3 reasoner/runtime
P1-C: hybrid typed IR + N3 import/export/independent validation
```

P0 expresses no production preference by implementation convenience. The deciding evidence should be deterministic equivalence, bounded reasoning, provenance fidelity, deployment simplicity and cross-domain reuse.

## 15. P0 architecture ruling

The audited system already contains enough semantic invariants to justify a first-class logic layer, but not enough evidence to hand it production authority.

The frozen architecture is therefore:

```text
model owns semantic choice
        |
semantic logic owns deterministic closure
        |
adapter owns physical grounding/actuation primitives
        |
runtime owns hard authority and durable execution boundaries
```

P0 stops at specification + frozen shadow oracles.
