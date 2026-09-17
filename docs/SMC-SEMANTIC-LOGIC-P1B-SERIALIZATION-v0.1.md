# SMC Semantic Logic P1-B Serialization Profile v0.1

> Status: **P1-B / shadow-only serialization contract**
> Parent qualification: `P1-A@6efd264224c8b3e00ef2d8b5c1e58bbb351a10cb`
> Production consumer: **none**
> N3 reasoner: **not required / not installed by P1-B**

## 1. Purpose

P1-B defines deterministic wire representations for the P1-A `FactGraph` without
changing SMC semantics or execution authority.

Two representations are frozen:

1. canonical JSON envelope;
2. canonical N3 document using a deliberately small full-IRI Turtle-compatible triple
   subset.

The current Python SMC implementation remains the semantic oracle. P1-B performs no
rule evaluation and makes no production decision.

## 2. Authority boundary

The serializers may only preserve already-materialized Typed IR state.

They may not:

- choose a target/action;
- infer task relevance or completion;
- resolve source conflicts;
- collapse `unknown` / `indeterminate` to false;
- refresh/rebind stale identities;
- grant runtime permission;
- dispatch physical effects;
- execute N3 rules or builtins;
- access network, files outside the caller-provided document, or subprocesses.

`production_consumed=false` remains explicit in both formats.

## 3. Canonical JSON profile

Profile ID:

```text
smc.fact_graph_json.v0.1
```

The top-level envelope is closed and contains:

```text
schema
profile
opaque_identity_policy
normalization
production_consumed
graph_fingerprint
graph
```

Required policy values:

```text
opaque_identity_policy = exact_literal_no_normalization
normalization          = none
production_consumed    = false
```

Canonical bytes use UTF-8, sorted JSON object keys, compact separators, finite JSON
numbers only, and one final newline. The loader rejects semantically equivalent but
non-canonical pretty/reordered bytes.

## 4. Canonical N3 profile

Profile ID:

```text
smc.fact_graph_n3.v0.1
```

Namespace:

```text
urn:smc:semantic-logic:v0.1#
```

P1-B intentionally uses a conservative syntax surface:

- one full-IRI triple per line;
- no prefix abbreviations;
- no blank nodes;
- no quoted graph/formula syntax yet;
- no implication/rule syntax yet;
- no builtin invocation;
- no remote import;
- lexicographically sorted unique statements;
- exactly one final newline.

This is a Turtle-compatible triple subset and therefore suitable as an N3 input
surface. Independent external reasoner parsing is **P1-C**, not a P1-B claim.

## 5. Stable entities

Qualification-critical entities never use anonymous identity.

P1-B emits deterministic URNs for:

- `TypedFactGraph`;
- `ContainerShape`;
- `SemanticFact`;
- `FactContext`;
- `FactProvenance`.

Graph/container URNs are SHA-256-derived from explicit canonical identity inputs.
Fact/context/provenance URNs are derived from the existing deterministic `fact_id`.

The original opaque runtime identities are still carried as exact literal values where
they existed in Typed IR. Hash-derived entity URNs do not replace or semantically
normalize those values.

## 6. Structural order

RDF/N3 triples are unordered, while the Typed IR container/fact tuples preserve a
deterministic projection order. P1-B therefore serializes an explicit non-semantic
`ordinal` for every `ContainerShape` and `SemanticFact`.

The ordinal exists only to make a lossless Typed-IR round trip possible. It does not
express world order or action priority.

## 7. Path representation

Fact/container paths are encoded as a canonical JSON lexical value with datatype:

```text
urn:smc:semantic-logic:v0.1#jsonPath
```

Each path segment is explicitly either:

```text
{"kind":"key","value":"..."}
```

or:

```text
{"kind":"index","value":0}
```

This avoids ambiguity between an object key such as `"0"` and an array index `0`.

## 8. Scalar representation

Typed IR scalar values map as follows:

| Typed IR | N3 object |
|---|---|
| null | `urn:smc:semantic-logic:v0.1#null` IRI |
| boolean | `xsd:boolean` typed literal |
| integer | `xsd:integer` typed literal |
| number | canonical JSON lexical form as `xsd:double` |
| string | `xsd:string` typed literal |

`valueType` is also serialized explicitly and must agree with the object encoding.

## 9. Context and provenance

Every `SemanticFact` links to a stable `FactContext` and `FactProvenance` entity.

Context carries, when present:

```text
domain
scopeRef
observedVersion
snapshotId
sensorContractRef
```

Provenance carries:

```text
kind=oracle_projection
source
groundingRef?
observedVersion?
```

The P1-A invariant that context/provenance `observed_version` agree remains enforced on
both decode paths.

## 10. Conflict, unknown and completeness honesty

P1-B does not invent a higher-level RDF truth model. It serializes the exact existing
Typed IR leaves.

Therefore:

- canonical conflict-null remains explicit null plus the source-qualified observations;
- `indeterminate` remains the exact string/status emitted by the Python oracle;
- source `dom` and `ax` facts remain separate;
- observation completeness and projection completeness remain separate FactPaths;
- partial coverage never creates an absence assertion;
- N3 success or parseability grants no execution authority.

## 11. Strict decode

Both loaders are intentionally stricter than a general-purpose parser.

Canonical JSON rejects:

- unknown/missing envelope fields;
- altered authority/policy values;
- bad `fact_id` integrity;
- type/path mismatches;
- non-canonical bytes.

Canonical N3 rejects:

- unsupported statement syntax;
- blank-node surfaces;
- duplicate/unsorted triples;
- unstable/mismatched entity URNs;
- non-contiguous structural ordinals;
- datatype/value-type mismatch;
- altered opaque-identity policy;
- graph fingerprint mismatch;
- any byte representation that does not reserialize identically.

## 12. P1-B qualification gate

P1-B is PASS only if all frozen P0/P1-A cases satisfy:

```text
FactGraph -> canonical JSON -> FactGraph == original
FactGraph -> canonical N3  -> FactGraph == original
reconstructed Python-oracle document == original
same normalized FactGraph -> identical JSON bytes
same normalized FactGraph -> identical N3 bytes
opaque identity normalization = none
production consumers = 0
external reasoner dependency = 0
```

P1-B does not authorize P1-C installation or P1-D semantic cutover.
