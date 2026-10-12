# SMC Semantic Logic P2 Design Result — 2026-09-17

> Status: **PASS / docs-only / shadow-only**
> Parent P1-D result: `54f1ed8c6c0b4cf71ca4b2bd39970df31d2e2ed5`
> Design commit: `97c77c25a9ad573176c567dc8a1cb1d961713296`
> RulePack: `smc.browser.p2-core.v0.1`
> RulePack hash: `bba3a38c315078e390d1afd985572c962bfcecf076ef9ff623abcdf34ace458b`
> Production consumer: **none**

## 1. Verdict

The P2 Core Rule Engine design boundary is qualified for RED-first implementation.
It freezes a closed Typed-IR engine with **13 fixed evaluator operations** across five
rule groups and **64 deterministic RED gates**. The engine is not a general N3/DSL
runtime and cannot dynamically load or execute model-authored rules.

The design preserves the P0 authority split: model semantic choice remains model-owned;
Semantic Logic may only derive deterministic closure; Adapter owns physical observation
and grounding; Runtime owns permission, reservation, locking, physical dispatch,
idempotency enforcement and durable receipt append.

## 2. Machine contract validation

```text
Draft 2020-12 schema              PASS
Rule hashes                       13 / 13 PASS
RulePack hash                     PASS
Rule dependency DAG               PASS
RED gate ids                      64 / 64 unique
P0 oracle fixture references      15 / 15 resolved
authority audit                   PASS
```

The exact RulePack hash is:

```text
bba3a38c315078e390d1afd985572c962bfcecf076ef9ff623abcdf34ace458b
```

## 3. Key architecture decisions

- P1 `FactGraph` remains a lossless representation layer; P2 rule inputs use the P0
  semantic-fact shape and keep asserted inputs separate from expected derived outputs.
- RulePack evaluation is one bounded topological pass; recursion/cycles are forbidden.
- `negation-as-failure` remains disabled. Missing evidence never means false.
- Negative existence requires an explicit capture-membership fact plus complete relevant
  coverage and stable identity.
- Runtime/Adapter facts may be premises but Semantic Logic cannot manufacture
  `runtime_authority` provenance.
- `execution_precondition_fact` output remains shadow-only throughout P2.
- N3 remains an independent restricted qualification plane; no arbitrary external rule
  input is opened.
- Pack/hash/bounds/evaluator faults reject the whole qualification result; partial
  derived facts cannot silently count as qualified.

## 4. Five frozen groups

```text
G1 Grounding                 2 rules
G2 Scope                     2 rules
G3 Completeness / Conflict   4 rules
G4 Predicate                 2 rules
G5 Version / Receipt         3 rules
Total                       13 rules
```

## 5. RED-first surface

The frozen manifest contains **64** RED gates spanning:

- exact grounding and fail-closed unauthorized/expired/wrong-kind/tampered cases;
- scope ancestry, mismatch, cycles and depth pressure;
- DOM/AX conflict, coverage, projection-vs-observation separation and no-fusion;
- complete/partial/unstable Predicate honesty and lower-bound reasoning;
- version lineage/staleness and receipt monotonicity/single-dispatch/no-retry;
- rulepack hash/schema/authority/output/DAG/bounds/domain/evaluator/determinism attacks.

The fixture contract explicitly forbids feeding an already-derived expected output back
as an asserted P2 input.

## 6. Committed-state qualification

Exact design commit `97c77c25a9ad573176c567dc8a1cb1d961713296` was requalified from committed state:

```text
P1 semantic adjacency             215 / 215 PASS
whole-tree security               1961 tracked files PASS
Ruff                              PASS
env-pin                           591 test files / 0 undeclared
Pyright                           0 errors / 0 warnings
tier0                             PASS
full xdist                        PASS
full ci_gate                      PASS
worktree                          clean
```

The fresh worktree initially lacked gitignored qualification `node_modules`; the P1-C/D
validator correctly failed closed with `pinned_backend_not_installed`. Reinstalling only
from the existing pinned lock via `npm ci --ignore-scripts` restored exact
`eyereasoner 21.1.18 / swipl-wasm 7.0.10 / n3 2.7.12`, did not modify Git state, and the
215-case adjacency then passed.

## 7. Asset hashes

- `docs/SMC-SEMANTIC-LOGIC-P2-CORE-RULE-ENGINE-v0.1.md` — `eb59b26b540b7197a00bb8b6a70615fb603c4dd82a15c9974c3f0dd14c971024`
- `docs/SMC-SEMANTIC-LOGIC-P2-RULEPACK-v0.1.json` — `97b37a9dcf12823a43058ea6663485e4dff60ed0071844fcc4eaedb53cad6268`
- `docs/SMC-SEMANTIC-LOGIC-P2-RED-GATES-v0.1.json` — `d5c681333299016d1ac6a9c58e0effa18ce98afdd82aa878512aba1833bf2475`
- `docs/SMC-SEMANTIC-LOGIC-P2-SCHEMA-v0.1.json` — `6eaa0333c10b458b71c459eef42f34e7e0c0b035749db7b2890d30f8d81ae83f`

Machine result:

```text
docs/SMC-SEMANTIC-LOGIC-P2-DESIGN-RESULT-20260917.json
sha256 = a31d1e813303d5a2dc1f1b19677d14d04be68a2bc1b8133308623e26a0e14d67
```

## 8. Boundary

The design is **ready for RED-first implementation**, but no P2 evaluator/test engine has
been implemented yet. No provider-visible schema, production Runtime consumer, routing,
mutation dispatch, completion authority, deployment, restart or local-model change is
part of this design qualification.

Per MCP architecture-gate discipline, implementation begins only after the owner accepts
this frozen design boundary.
