# SMC Semantic Logic P1-D Result — 2026-09-17

> Status: **PASS / shadow-only**
> Parent P1-C result: `ec548709a3ee7286a4dcd3397538f39ff7741709`
> Implementation commit: `bc3f72d169636b5fc3ab9e54d9f866fd478ab553`
> Branch: `feature/smc-semantic-logic-p1d-20260917`
> Production consumer: **none**

## 1. Verdict

P1-D passes the frozen three-plane representation gate.

For all 15 frozen S1-S5 fixtures:

```text
Plane A = frozen Python canonical oracle direct traversal
Plane B = Typed FactGraph direct field projection
Plane C = actual restricted EYE output parsed independently by pinned n3@2.7.12

A == B == C: 15 / 15
false closure: 0
unknown -> false collapse: 0
source/provenance loss: 0
context/version loss: 0
```

This remains representation/shadow qualification. It does **not** promote N3, Typed IR,
or any rule engine into production authority.

## 2. Common-mode controls

P1-D deliberately uses three different extraction paths. Plane A does not call
`project_document`; Plane B does not reconstruct the Python document; Plane C consumes
real EYE `--pass` output and parses that output in JavaScript.

The narrow S2/S3/S4/S5 sentinel queries are fixed in the JS bridge, but their expected
hits are frozen independently in Python. The JS query implementation therefore cannot
grade itself. Four sentinel fixtures matched their independent expectations exactly.

## 3. Backend identity

```text
EYE package: eyereasoner 21.1.18
EYE runtime: EYE v11.24.5 (2026-08-23)
swipl-wasm: 7.0.10
Node: v24.18.0
package-lock sha256: 83d2ee38f112bea8929751a5a2c31dede5aec07312eb696ce660537d288c71be
Plane-C parser: n3 2.7.12
Plane-C parser integrity: sha512-Hy6dfGg9yniLQpSBirvH2E2yO3EG7dSmA3aefRbtO411oqtzG8roD3h1kTc/N065bivCOPfTFIjf0KlwW7KlnQ==
```

The P1-C sandbox remains in force: network, host file write, and child-process effects
are denied; backend execution remains restricted and bounded.

## 4. Frozen gate totals

```text
cases required / observed        = 15 / 15
relation-equivalent cases        = 15
Plane-B added / missing           = 0 / 0
Plane-C false closure / missing   = 0 / 0
unknown->false collapse           = 0
source/provenance loss            = 0
context/version loss              = 0
sentinel fixtures exact           = 4 / 4
```

## 5. Qualification

```text
P1-D focused                  25 / 25 PASS
Browser semantic oracle      119
P1-A Typed IR                 21
P1-B serialization            26
P1-C restricted validator     24
P1-D three-plane              25
combined                     215 / 215 PASS
whole-tree security          1955 tracked files PASS
env-pin                       591 / 0 undeclared
Pyright                       0 errors / 0 warnings
full ci_gate                  PASS
```

## 6. Exact implementation surface

P1-D implementation commit changes exactly three qualification-only paths:

```text
tools/semantic_logic/p1d_qualification.py
tools/semantic_logic/n3_validator/p1d_bridge.mjs
tests/unit/test_smc_semantic_logic_p1d.py
```

No file under `src/llm_loop` is changed by P1-D.

## 7. Machine result

```text
docs/SMC-SEMANTIC-LOGIC-P1D-RESULT-20260917.json
sha256 = 6fd373c72e1cc127b31c002d7cc259781db724f92e81d465fc759505fc850e3b
```

The machine result contains all 15 per-case relation counts/loss metrics plus the four
sentinel hit sets.

## 8. Phase boundary

P0 + P1-A + P1-B + P1-C + P1-D are now qualified as the **Hybrid representation and
shadow-validation foundation**.

Still not authorized by P1-D:

```text
P2 Core Rule Engine
semantic-rule production authority
provider-visible routing changes
mutation authority
completion authority
N3 direct authority
production deployment
```

The next architectural phase is P2 and requires a separate owner decision.
