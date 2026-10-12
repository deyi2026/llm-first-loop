# SMC Semantic Logic P1 Architecture Decision v0.1

> Status: **P1-A0 / architecture decision / docs-only**
> P0 baseline: `main@19e253edfe4d3fcbeb268830b90d00fd273a6262`
> Production consumption: **none**
> Decision: **Hybrid typed IR + N3 validation is the preferred P1 candidate**
> Production authority during P1-P3: **unchanged; current Python canonical path remains authoritative**

## 1. Decision

P1 will not make a direct N3 reasoner the canonical SMC runtime.

The preferred architecture is:

```text
SMC canonical objects / frozen fixtures
                |
                v
        Typed Semantic IR
                |
        +-------+--------+
        |                |
        v                v
 deterministic       deterministic
 typed projection    N3 serialization
        |                |
        v                v
 ShadowResult       isolated N3 validator
        |                |
        +-------+--------+
                |
                v
       frozen Python oracle compare
```

The authority ruling is deliberately asymmetric:

```text
Typed IR
  = canonical internal representation candidate

N3
  = independent logic/serialization/proof validation plane

Runtime
  = unchanged hard authority owner
```

N3 is therefore a **validator and research interoperability plane**, not a second production authority path.

## 2. Why Hybrid is preferred

P0 established five facts that materially constrain the choice:

1. SMC needs typed context, source, version, completeness and provenance; triples alone are insufficient.
2. `unknown != false` and source conflict honesty are hard semantic requirements, not presentation preferences.
3. opaque runtime identities make naïve byte-for-byte graph comparison invalid.
4. execution authority belongs to Runtime and must not be minted by a semantic reasoner.
5. Browser, SMX and FileService already expose homologous semantic invariants that should converge without forcing one physical representation across domains.

Hybrid preserves these requirements while gaining N3's graph/rule/proof ecosystem as a second implementation lens.

## 3. Compared alternatives

### 3.1 P1-A — Typed IR only

Shape:

```text
SMC -> typed FactGraph -> typed RulePack -> typed evaluator
```

Strengths:

- strongest Python type/control integration;
- easiest deterministic serialization and hash pinning;
- easiest bounded execution and resource accounting;
- no new runtime dependency;
- direct mapping to existing P0 JSON Schema;
- easiest to preserve current reason codes and exact closed contracts.

Weaknesses:

- risks becoming a bespoke logic system;
- weaker external interoperability;
- fewer independent checks against mistakes in the evaluator;
- proof/graph tooling must be built or adapted internally.

Ruling:

> Safe fallback and likely canonical representation, but insufficient by itself to test whether the abstraction is genuinely logic-portable rather than merely a refactoring of existing Python.

### 3.2 P1-B — Direct N3 reasoner/runtime

Shape:

```text
SMC -> N3 graph/rules -> reasoner -> canonical SMC output
```

Strengths:

- native graph/rule expression;
- quoted graph/context/provenance concepts are natural;
- external reasoners can emit inspectable proofs;
- strong Semantic Web interoperability;
- forward/backward reasoning is already part of the N3 model.

Weaknesses for current LFL/SMC:

- would immediately couple canonical behavior to an external reasoner/runtime;
- reasoner concrete syntax, builtin behavior and proof formats become production compatibility surfaces;
- N3 scoped negation-as-failure is more expressive than SMC's current open-world honesty and could cause false closure if not tightly fenced;
- online/file builtins are incompatible with SMC shadow isolation unless explicitly disabled;
- rule recursion and term generation require additional boundedness controls;
- mapping SMC typed reason/status/completeness contracts back out of generic graph entailments adds another authority-sensitive translation layer;
- current repository/runtime has no existing N3/EYE/RDF Python dependency to reuse.

Ruling:

> Valuable experiment arm, but too early to make canonical. The current evidence does not justify moving SMC authority behind a reasoner-specific runtime boundary.

### 3.3 P1-C — Hybrid typed IR + N3 validation

Shape:

```text
canonical SMC
   -> typed FactGraph / RulePack
       -> typed deterministic projection
       -> canonical N3 artifact
           -> isolated reasoner/validator

all outputs -> frozen Python oracle / ShadowResult comparator
```

Strengths:

- typed IR retains exact SMC contracts and authority classes;
- N3 validates portability of the logic abstraction;
- reasoner proof output can cross-check DerivationRecord chains;
- direct reasoner failure cannot mutate production behavior;
- external reasoner can remain qualification-only;
- no N3 dependency is required on Web/Feishu/model-serving hot paths;
- a future second reasoner can be added without changing the canonical IR;
- makes eventual cross-domain Browser + Filesystem validation easier.

Main risk:

> A generated N3 artifact and the typed evaluator can share the same wrong RuleSpec, producing a common-mode false green.

Mitigation is specified in section 8.

Ruling:

> **Preferred P1 candidate.** It gives SMC an explicit logic interoperability plane without surrendering typed deterministic control or Runtime authority.

## 4. Project-specific decision matrix

Scores are design-decision aids, not universal claims about N3. `5` means best fit for the current P0 requirements.

| Criterion | Weight | Typed IR | Direct N3 | Hybrid |
|---|---:|---:|---:|---:|
| deterministic closed contract | 20 | 5 | 3 | 5 |
| authority isolation / LLM-First fit | 15 | 5 | 3 | 5 |
| provenance / proof fidelity | 15 | 4 | 5 | 5 |
| bounded execution / fail-closed control | 15 | 5 | 3 | 5 |
| deployment simplicity | 10 | 5 | 2 | 4 |
| cross-domain reuse | 10 | 4 | 4 | 5 |
| standards / research interoperability | 10 | 2 | 5 | 5 |
| independent implementation validation | 5 | 2 | 5 | 5 |

Weighted decision signal:

```text
Typed IR   ~= 4.30 / 5
Direct N3  ~= 3.60 / 5
Hybrid     ~= 4.90 / 5
```

This score does **not** authorize implementation cutover. It selects the P1 experiment architecture.

## 5. Canonical Hybrid architecture

### 5.1 Typed IR plane

The P0 entities remain canonical:

```text
SemanticFact
Context
Provenance
SemanticRule
RulePack
DerivationRecord
ShadowResult
```

Required design properties:

- immutable/frozen value objects where practical;
- closed enums for truth/authority/status classes;
- deterministic field ordering for canonical serialization;
- explicit nullable/unknown states rather than missing-field inference;
- content-addressed IDs where identity is semantic;
- opaque runtime IDs remain explicitly opaque and are never semantic-normalized;
- no access to model/task semantics from the evaluator.

### 5.2 N3 serialization plane

Typed IR must have a deterministic N3 representation.

The N3 artifact is a projection of exact typed facts and rules, not a second source of authority.

Requirements:

1. stable namespace/version declaration;
2. no anonymous blank-node identity for qualification-critical entities;
3. stable IRIs/URNs for facts, contexts, derivations and rules;
4. explicit context/version/source/provenance edges;
5. source-qualified conflicting facts remain distinct statements;
6. canonical unknown/conflict state is represented explicitly;
7. observation completeness and projection completeness remain different predicates;
8. rule hash/version/authority class are represented;
9. serialized N3 bytes are deterministic for the same normalized typed input;
10. N3 round-trip may not invent stronger truth than the typed IR contains.

### 5.3 N3 validation plane

Initial N3 validation is **qualification-only**.

It may:

- parse canonical N3 artifacts;
- evaluate explicitly allowed local rules;
- answer frozen entailment/non-entailment queries;
- emit proof material;
- compare derived relations with typed ShadowResults.

It may not:

- access network resources;
- read arbitrary local files;
- execute shell/process effects;
- route tools/models;
- choose semantic targets/actions;
- mutate Browser/FS/runtime state;
- mint Runtime authority;
- feed production canonical output during P1-P3.

## 6. N3 safety profile

The validator must use an SMC-specific restricted profile rather than 'all N3 features are allowed'.

### 6.1 Forbidden by default

```text
remote imports
online knowledge retrieval
file access builtins
process/system effects
unbounded recursive term generation
implicit authority from successful entailment
```

### 6.2 Negation rule

N3 supports scoped negation-as-failure, but SMC must not translate generic absence into false.

Therefore:

```text
notIncludes / negation-as-failure
```

is forbidden for canonical SMC absence derivation unless the input Rule declares a matching `closed_world_requirement` and the exact required coverage fact is present.

Example:

```text
missing(target)
+ complete(relevant_scope)
+ stable_identity(target)
=> exists(target)=false
```

Without all required premises:

```text
=> indeterminate
```

### 6.3 Bound profile

Every validator run must be mechanically bounded by:

- local-only input set;
- rulepack hash;
- fixture hash;
- wall timeout;
- output/proof byte cap;
- answer count cap;
- recursion/fixpoint cap where supported;
- forbidden-builtin scan before execution.

The validator backend ID/version and exact flags must be recorded in the qualification receipt.

## 7. Validator backend policy

P1 must define an abstract validator interface. Do not make the Typed IR API depend on one reasoner.

Conceptual interface:

```text
validate(
  n3_document,
  query_set,
  restricted_profile,
  bounds
) -> N3ValidationReport
```

First candidate backend: **EYE**, because its current tooling exposes proof-oriented reasoning plus a `--restricted` mode and answer/tactic limits.

This is a qualification choice, not a permanent production dependency.

Current local environment fact at P1-A0 audit:

```text
eye: not installed
swipl: not installed
canonical project .venv rdflib: not installed
Node: available
```

Therefore P1 must not silently add a reasoner to the production dependency graph. Any external validator installation/containerization is a separate, pinned qualification step.

## 8. Avoiding common-mode false green

Hybrid only adds value if N3 is not a decorative serialization of the same buggy result.

Use three independent evidence planes:

```text
Plane A: existing frozen Python canonical oracle
Plane B: new Typed IR / typed projection
Plane C: N3 reasoner validation/proof
```

Rules:

1. Plane A remains the P1/P2 semantic truth oracle.
2. Plane B and C are compared independently to A.
3. Typed evaluator output must never be used as the expected answer for N3 validation.
4. N3 serialization may be generated from the typed RuleSpec, but selected critical invariants require independent sentinel queries.
5. A mismatch in either B or C is RED.
6. B=C but A differs is still RED.

Independent sentinel queries should at least cover:

```text
S2: conflict must not entail either conflicting source value as canonical truth
S3: partial coverage must not entail exists=false
S3: complete coverage + stable identity may entail exists=false
S4: document generation change must not entail version match
S5: duplicate exact action trace must not entail a second physical dispatch
```

These sentinel queries are deliberately narrow and do not duplicate the full RulePack.

## 9. P1 phase boundary

P1 remains representation/validation work. It does **not** absorb the P2 Core Rule Engine phase.

### P1-A — Typed FactGraph IR

Implement closed typed objects corresponding to P0 schema.

Gate:

```text
15 frozen cases project into typed IR without semantic loss
schema validation = 100%
no production consumer
```

### P1-B — Canonical serialization

Implement:

```text
typed IR -> canonical JSON
typed IR -> canonical N3
```

Gate:

```text
same normalized input -> same serialized bytes
opaque identity mapping rules explicit
round-trip relation preservation = 100%
```

### P1-C — Restricted N3 validator harness

Implement the validator interface and one pinned backend only in qualification/shadow scope.

Gate:

```text
network/file/effect capabilities disabled
backend/version/flags recorded
timeout/output/answer bounds enforced
unsafe fixture -> fail closed
```

### P1-D — Representation three-way qualification

For all 15 P0 fixtures compare:

```text
Python canonical relation set
vs
Typed IR relation set
vs
N3 parsed/entailed relation set
```

Gate:

```text
15/15 relation-equivalent
false closure = 0
unknown->false collapse = 0
source/provenance loss = 0
context/version loss = 0
```

P1-D does not require replacing current Python semantic derivation. Full rule execution parity remains P2/P3.

## 10. P2 implication

If P1 Hybrid qualifies, P2 should implement the actual Core Rule Engine in the Typed IR plane and use N3 as an independent shadow validator.

P2 five rule groups remain unchanged:

1. Grounding;
2. scope;
3. completeness/conflict;
4. Predicate;
5. version/receipt.

For each group:

```text
Python oracle == Typed evaluator == N3 validation
```

subject to the frozen opaque-identity isomorphism rules.

## 11. When to fall back to Typed IR-only

Hybrid should fall back to Typed IR-only for production architecture if any of the following persists after bounded engineering effort:

- N3 serialization cannot preserve context/provenance without fragile encoding conventions;
- reasoner outputs are not deterministic enough for frozen qualification;
- proof output cannot be stably mapped to DerivationRecord;
- validator sandbox/bounds cannot be proven;
- N3 adds material dependency/latency/operational complexity without catching independent defects;
- cross-reasoner semantic variance is material for the selected rule subset.

Falling back does not invalidate the Typed IR work.

## 12. When Direct N3 may be reconsidered

Direct N3 can be reconsidered only after Hybrid has already proved all of:

1. full S1-S5 semantic parity;
2. bounded local reasoning;
3. stable proof/provenance mapping;
4. deterministic reason/status mapping;
5. no false closure on adversarial unknown/partial cases;
6. acceptable latency/resource cost;
7. portable behavior across at least Browser + Filesystem;
8. mechanical rollback to Typed/Python authority;
9. explicit separate owner authorization.

Even then, N3 may never replace Runtime ownership of permission, locking, reservation, idempotency enforcement, physical dispatch or durable receipt append.

## 13. P1-A0 ruling

The preferred candidate is frozen as:

> **Hybrid typed IR + N3 validation, with Typed IR as the canonical internal semantic representation candidate and N3 as a restricted, independent, shadow-only validation/proof plane.**

This decision is intentionally reversible:

- if N3 proves valuable, it remains a strong independent verifier and interoperability layer;
- if N3 proves operationally weak, Typed IR remains independently useful;
- if future evidence eventually justifies Direct N3, the typed IR provides a stable adapter/rollback boundary rather than forcing a wholesale rewrite.

P1-A0 changes no production behavior and grants no new authority.

## 14. External references reviewed for P1-A0

These references are informative evidence for language/runtime properties. They are not SMC authority sources.

- W3C N3 Community Group, Notation3 Language: `https://w3c.github.io/N3/spec/`
- W3C N3 Community Group, Notation3 Semantics: `https://w3c.github.io/N3/spec/semantics.html`
- W3C N3 Community Group home: `https://www.w3.org/community/n3-dev/`
- EYE command-line documentation: `https://github.com/eyereasoner/eye/blob/master/documentation/command_line.md`

P1-A0 specifically relies on the following externally documented facts:

- N3 is currently published by the W3C N3 Community Group and is not a W3C Standards Track specification;
- the N3 semantics work explicitly separates abstract syntax from concrete syntax, including to isolate historical ambiguity around implicit quantification;
- N3 supports graph terms, logical implication, builtins and scoped negation-as-failure;
- EYE exposes proof-oriented execution plus a restricted mode and bounded-answer/tactic controls useful for a qualification validator.
