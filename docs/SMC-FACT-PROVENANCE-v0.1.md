# SMC Fact & Provenance Contract v0.1

> Status: **P0 / docs-only / shadow design**
> Baseline: `main@19e253edfe4d3fcbeb268830b90d00fd273a6262`
> Production consumption: **none**

## 1. Purpose

This document freezes the fact/context/provenance model for a future N3-compatible Semantic Logic Layer.

The design goal is not to make every SMC payload RDF/N3. The goal is to preserve the semantic properties that N3-style reasoning makes explicit:

- facts are source-qualified;
- facts live in explicit observation/version contexts;
- absence is not automatically negation;
- derivations preserve their premises and rule identity;
- old observations remain immutable;
- derived facts are distinguishable from observed facts and runtime authority facts.

## 2. Fact model

The minimum internal fact shape is:

```text
Fact
  fact_id
  domain
  subject
  predicate
  value
  value_type
  truth_state
  context
  provenance
```

### 2.1 `truth_state`

Closed vocabulary:

```text
asserted
unknown
conflict
not_applicable
```

No floating model confidence score is part of the core contract.

`false` is a typed value of an asserted fact, not an alias for `unknown`.

### 2.2 Subject identity

Subjects MUST use canonical semantic identity, scope identity, action identity, or a source-qualified observation identity. Raw CSS/XPath/coordinates/ephemeral array positions are not semantic subjects.

Examples:

```text
el_<semantic-id>
browser-page-scope:<opaque>
act-<id>
source-observation:<opaque>
```

## 3. Observation context

Every observation-derived fact MUST bind to an explicit context.

Minimum context:

```text
domain
scope_ref
observed_version
snapshot_id (when the domain has snapshots)
sensor_contract_ref (when applicable)
```

Browser example:

```text
context(snapshot_101) {
  button.enabled = true
}
```

Later observation:

```text
context(snapshot_102) {
  button.enabled = false
}
```

`snapshot_102` does not rewrite `snapshot_101`.

## 4. Source-qualified facts

Canonical projection MUST NOT erase source disagreement.

Conceptual source graphs:

```text
DOM(snapshot_101) {
  button.enabled = true
}

AX(snapshot_101) {
  button.enabled = false
}
```

If no frozen, task-independent mechanical resolver exists, the canonical result is:

```text
button.enabled = unknown
truth_state = conflict
```

and the provenance retains both observations.

This mirrors current C28 behavior: canonical field `null`, unresolved conflict, source/value/GroundingRef retained.

## 5. Provenance kinds

Closed `provenance.kind` vocabulary:

### `observed`

Direct adapter/sensor fact.

Required provenance fields:

```text
source
grounding_ref
observed_version
```

### `mechanically_derived`

Output of a frozen deterministic rule.

Required:

```text
derivation_ref
rule_ref
input_fact_refs
```

### `runtime_authority`

Fact emitted by a runtime hard-boundary owner, e.g. mutation authority or reservation state.

Semantic Logic can reference this fact but cannot mint it.

### `model_asserted`

Optional non-authoritative semantic statement authored by a model.

It MUST NOT be treated as observed or runtime-authoritative by merely changing namespace or serialization.

## 6. GroundingRef contract

The existing SMC GroundingRef contract remains authoritative.

A persistent grounding reference is:

1. scope-bound;
2. observation/version-bound;
3. session/authority-bound when the adapter requires it;
4. integrity-checkable when immutable grounding is claimed;
5. hydratable within the declared retention window;
6. non-rebinding: expired/unavailable/unauthorized does not trigger silent recapture or similar-target substitution.

Semantic Logic MUST preserve the exact `grounding_ref` as provenance. It MUST NOT derive a new physical locator and pretend it is the same grounding.

## 7. Observation completeness vs projection completeness

The two axes remain separate.

### Observation completeness

Answers:

> Did the declared sensor/adapter observe its declared scope completely enough for this mechanical claim?

Examples of reasons for incompleteness:

- truncated DOM;
- cross-origin frame;
- canvas/closed shadow root blind spot;
- walk error;
- missing sensor.

### Projection completeness

Answers:

> Did the current model-facing representation expand all data that was already captured?

Projection truncation does not change physical observation completeness. Exact hydration of a partial projection does not repair an original observation blind spot.

## 8. Open-world / negative fact discipline

Default rule:

```text
not observed != false
```

Negative closure is allowed only when a frozen rule proves the relevant observation coverage is sufficient.

Examples:

### Valid negative

```text
stable target previously known
+ current relevant scope observed completely
+ target absent
=> exists=false
```

### Invalid negative

```text
target absent
+ DOM truncated
=> indeterminate
```

### Unknown identity

```text
invented Semantic ID absent
=> indeterminate
```

because the system has no grounded basis that such an identity ever belonged to the observed world.

## 9. Lower-bound facts

Incomplete coverage does not erase positive witnesses.

Example:

```text
observed_count = 3
coverage incomplete
```

This supports:

```text
object_count >= 2  -> satisfied
```

but does not support:

```text
object_count <= 100 -> satisfied
```

unless complete coverage is available.

This distinction MUST be representable in derivation provenance.

## 10. Identity provenance

Stable semantic identity is not name similarity.

Identity facts must preserve the mechanical basis used by the adapter, including relevant generation/scope facts.

Current Browser principles frozen into P0:

- reorder of the same stable physical identity may preserve Semantic ID;
- same name/role on a replacement physical object does not preserve Semantic ID;
- duplicate same-name candidates do not merge by similarity;
- document/frame/runtime generation changes can invalidate identity lineage;
- snapshot-local AX identity is explicitly unstable and cannot support exhaustive create/remove or version-guard claims.

## 11. Diff provenance

A SemanticDiff is a relation between explicit observation contexts, not an eternal mutation record.

Minimum provenance includes:

```text
from_version
to_version
from_scope_ref
to_scope_ref
from_sensor_contract
to_sensor_contract
diff_semantics
comparability basis
```

If scope/document/sensor comparability fails, created/removed/changed MUST remain unknown where current SMC requires it.

## 12. DerivationRecord

Every mechanically derived fact in the future rule engine MUST have a derivation record.

Minimum shape:

```text
derivation_id
rule_id
rule_version
rule_hash
input_fact_refs
output_fact_refs
context_refs
result
reason
```

`input_fact_refs` MUST be sufficient to replay the mechanical conclusion without consulting hidden model reasoning.

## 13. Proof chain

The intended chain is:

```text
derived fact
  -> DerivationRecord
  -> frozen Rule identity
  -> input facts
  -> GroundingRef / runtime-authority source
  -> immutable observation or durable receipt
```

This is the P0 meaning of **proof-carrying semantic manipulation**.

It is a mechanical provenance chain, not a formal proof that the user's semantic objective was correct or achieved.

## 14. Receipt provenance

ActionReceipt facts have two distinct meanings:

1. execution/process facts: reserved, running, acknowledged/failed/rejected;
2. observed effects: before/after snapshots and SemanticDiff.

The receipt status MUST NOT be interpreted as task completion.

Running and terminal revisions are separate immutable receipt records under the same action identity with monotonic sequence.

## 15. File-domain cross-check

The existing FileService provides an important non-Browser precedent:

- immutable `snapshot_ref`;
- exact byte identity;
- workspace/path binding;
- version precondition;
- stale content -> `VersionConflict`;
- stable path lock and runtime effect authority;
- no task semantics in the file service.

Therefore the future Fact/Provenance model MUST be domain-neutral enough to represent both Browser GroundingRef and file snapshot references without pretending their physical identity schemes are identical.

## 16. Shell/SMX cross-check

Current SMX SMC projection already distinguishes:

- scope relation;
- observation completeness;
- projection completeness;
- snapshot-pair diff semantics;
- Predicate result;
- receipt grounding.

This supports elevating completeness, scope, version/context, and provenance concepts to SMC Core while leaving sensor-specific facts domain-owned.

## 17. Privacy

Provenance MUST NOT imply raw secret retention.

Existing precedent is retained:

- sensitive fill/select/navigation args may persist length/hash rather than plaintext;
- raw private locators may remain adapter-private;
- GroundingRef may resolve to a privacy-safe canonical projection rather than raw backend state;
- proof completeness must honestly state when raw grounding is unavailable.

## 18. P0 ruling

Facts are not context-free triples. The future logic layer must reason over:

```text
fact + source + scope + version + completeness + provenance
```

Any N3-compatible representation chosen in P1 must preserve those dimensions without relying on implicit current-state mutation or closed-world assumptions.
