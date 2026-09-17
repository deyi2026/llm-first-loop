# SMC Semantic Logic P1-B Result — 2026-09-17

> Status: **PASS / shadow-only**
> Parent P1-A result: `6efd264224c8b3e00ef2d8b5c1e58bbb351a10cb`
> Implementation commit: `27bd31c8a4f03602987eaeb2c8f96baed68aa9f5`
> Branch: `feature/smc-semantic-logic-p1b-20260917`
> Production consumer: **none**
> External N3 reasoner: **not installed / not used**

## 1. Verdict

P1-B passes its frozen gate.

The P1-A Typed FactGraph now has two deterministic shadow serializations:

1. `smc.fact_graph_json.v0.1` canonical JSON;
2. `smc.fact_graph_n3.v0.1` canonical N3 input surface implemented as a restricted
   full-IRI Turtle-compatible triple subset.

For all 15 frozen S1-S5 cases:

```text
FactGraph -> canonical JSON -> FactGraph == original
FactGraph -> canonical N3  -> FactGraph == original
reconstructed Python-oracle document == original
same concrete FactGraph -> identical JSON bytes
same concrete FactGraph -> identical N3 bytes
opaque identity normalization = none
```

This is a serialization qualification only. P1-B does not claim independent external
N3 reasoner parsing, entailment, proof generation, or production authority.

## 2. Exact implementation identity

P1-B implementation/spec commit:

```text
27bd31c8a4f03602987eaeb2c8f96baed68aa9f5
```

Direct parent:

```text
6efd264224c8b3e00ef2d8b5c1e58bbb351a10cb
```

The committed P1-B change consists of exactly four paths:

```text
docs/SMC-SEMANTIC-LOGIC-P1B-SERIALIZATION-v0.1.md
src/llm_loop/semantic_logic/__init__.py
src/llm_loop/semantic_logic/serialization.py
tests/unit/test_smc_semantic_logic_p1b.py
```

Committed file hashes:

```text
b9a632a8f546ce964a6ae0bc4f2bfb1a77e1ac22f1afae585d9185b86afddc54  src/llm_loop/semantic_logic/__init__.py
97e4386fbdf21c5404c28e5381aefea2a72826bf4199c97c0d8c96010cd12504  src/llm_loop/semantic_logic/serialization.py
2ec9b29764955f2e15b50d8418ff4788bbe6d5a3a8878a67394531d081416cda  tests/unit/test_smc_semantic_logic_p1b.py
ebc66ad3fd4588fcbc0cfd0655427d456d383b7c1d8ec5666d8fc1d2d803b9f8  docs/SMC-SEMANTIC-LOGIC-P1B-SERIALIZATION-v0.1.md
```

## 3. Canonical JSON result

The JSON serialization is a closed envelope containing:

```text
schema
profile
opaque_identity_policy
normalization
production_consumed
graph_fingerprint
graph
```

Qualification-critical policy is explicit:

```text
profile                = smc.fact_graph_json.v0.1
opaque_identity_policy = exact_literal_no_normalization
normalization          = none
production_consumed    = false
```

The loader rejects:

- pretty/non-canonical byte forms;
- unknown or missing envelope fields;
- mutated authority or identity policy;
- bad fact-id integrity;
- type/path inconsistencies;
- graph-fingerprint mismatch.

## 4. Canonical N3 result

P1-B freezes the N3 profile:

```text
smc.fact_graph_n3.v0.1
```

The representation deliberately stays inside a small deterministic surface:

- full IRIs only;
- one triple per line;
- sorted unique statements;
- no blank nodes;
- no prefix abbreviations;
- no quoted graph/formula syntax;
- no implication or rule syntax;
- no builtin calls;
- no remote imports;
- stable URNs for graph/container/fact/context/provenance entities;
- exact opaque runtime identities remain literals, not normalized aliases.

The local decoder reconstructs the exact Typed FactGraph and rejects non-canonical
order, duplicates, blank-node syntax, policy drift, entity-IRI drift, datatype mismatch,
ordinal inconsistency, fingerprint mismatch, and byte drift.

Independent parsing by EYE/another pinned reasoner is intentionally deferred to P1-C.

## 5. Frozen-case qualification

P1-B reuses the exact P1-A case builders and P0 manifest; it does not create a second
handwritten semantic oracle.

Frozen distribution:

| Gate | Cases |
|---|---:|
| S1 Grounding Closure | 3 |
| S2 C28 Source Conflict | 2 |
| S3 Predicate Honesty | 3 |
| S4 Version/Staleness | 4 |
| S5 Receipt Monotonicity/Single Dispatch | 3 |
| **Total** | **15** |

Across those 15 cases the concrete Typed IR contained:

```text
facts_total      = 726
containers_total = 209
```

Both canonical formats round-tripped every case exactly.

## 6. Serialization size observation

This is a byte-size observation, not a latency benchmark.

Across the 15 frozen concrete cases:

| Surface | Total bytes | Min/case | Max/case |
|---|---:|---:|---:|
| canonical JSON | 437,392 | 4,877 | 83,156 |
| canonical N3 | 2,731,339 | 30,938 | 516,785 |

The N3 representation is materially larger for the current verbose proof-friendly
shape. This supports the existing architecture decision: N3 remains a
qualification/proof/interoperability plane rather than a production hot-path wire format.

No performance or cost claim beyond serialized byte size is made here.

## 7. Semantic-honesty checks

Focused P1-B tests verify that serialization preserves, rather than reinterprets:

- DOM/AX source-qualified conflicts;
- canonical null under unresolved conflict;
- exact `indeterminate` status;
- GroundingRef/provenance literals;
- observed-version context;
- observation completeness separately from projection completeness;
- JSON scalar type distinctions;
- structural empty dict/list containers;
- exact opaque identities.

The serializers contain no semantic-rule evaluation and therefore cannot turn missing
information into false, resolve conflicts, or mint execution permission.

## 8. Focused and adjacent tests

P1-A + P1-B serialization suite:

```text
47 / 47 PASS
```

Original frozen Browser semantic oracle plus P1-A + P1-B:

```text
119 original Browser oracle
+21 P1-A Typed IR
+26 P1-B serialization
=166 / 166 PASS
```

The first P1-B test run had one test-only false red: it searched the raw N3 lexical
surface for an unescaped JSON-path string. N3 correctly escaped the inner JSON literal,
and the FactGraph round-trip had already succeeded. The test was corrected to assert the
decoded exact `FactPath`; no production/serializer semantic change was needed for that
failure.

## 9. Static and whole-repository qualification

Committed implementation state `27bd31c8...`:

```text
Ruff                       PASS
Pyright                    0 errors / 0 warnings
py_compile                 PASS
git diff --check           PASS
production consumer scan   0 imports outside semantic_logic
```

Formal full gate:

```text
PY=../../.venv/bin/python bash scripts/ci_gate.sh
```

Result:

```text
full Ruff                  PASS
env-pin                    589 test files / 0 undeclared
Pyright                    0 errors / 0 warnings
tier0                      PASS
full xdist                 PASS
ci_gate                    PASS
```

Whole-tree security scan:

```text
1941 tracked files PASS
```

Worktree after committed implementation qualification:

```text
clean
```

## 10. Dependency and authority audit

P1-B adds no external reasoner dependency.

The serializer module imports no:

```text
rdflib
requests
httpx
socket
subprocess
eye
swipl
```

The `http://www.w3.org/...` strings are fixed datatype vocabulary IRIs only; P1-B never
dereferences them.

No source file outside `src/llm_loop/semantic_logic/` imports the Semantic Logic package.
Therefore production consumer count remains exactly zero.

## 11. Non-effects

P1-B performed none of the following:

```text
provider-visible schema change
Browser/SMX/FileService behavior change
mutation-authority change
runtime-authority change
N3 reasoner installation
network qualification
push
deploy
service restart
8901/model restart or switch
```

## 12. Boundary after P1-B

P1-B is complete only as a deterministic representation layer.

Not started:

```text
P1-C restricted/pinned N3 validator harness
P1-D three-way Python/Typed/N3 qualification
P2 Core Rule Engine
production authority cutover
```

P1-C is a separate phase because it introduces an external validator/runtime sandbox and
must prove effects-disabled, bounded, pinned behavior before any N3 entailment result is
trusted even as shadow qualification evidence.
