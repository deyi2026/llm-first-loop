# SMC Semantic Logic P1-C Result — 2026-09-17

> Status: **PASS / restricted shadow-only validator**
> Parent P1-B result: `7cc6433aa8012636d49795b070a36392a5d06ddb`
> Implementation commit: `59f66d678662cd9a255067084c05841a5692c830`
> Branch: `feature/smc-semantic-logic-p1c-20260917`
> Production consumer: **none**
> Production authority: **unchanged**

## 1. Verdict

P1-C passes its frozen restricted-validator gate.

The qualification plane now has one pinned external N3 backend that accepts only the
strict P1-B canonical N3 surface and runs outside `src/llm_loop`.

The qualified boundary is intentionally narrow:

```text
P1-B canonical N3 bytes
        |
        v
strict local canonical preflight
        |
        v
pinned EYE-js / SWI-Prolog WASM
        |
        v
macOS Seatbelt restricted qualification sandbox
        |
        v
hash-only bounded validation receipt
```

P1-C does **not** enable N3 rules, model-facing queries, production routing, mutation,
completion judgment, provider-visible behavior, or runtime authority.

## 2. Exact implementation identity

Implementation commit:

```text
59f66d678662cd9a255067084c05841a5692c830
```

Direct parent:

```text
7cc6433aa8012636d49795b070a36392a5d06ddb
```

The implementation commit contains exactly seven qualification-only paths:

```text
tests/unit/test_smc_semantic_logic_p1c.py
tools/semantic_logic/n3_validator/.gitignore
tools/semantic_logic/n3_validator/bridge.mjs
tools/semantic_logic/n3_validator/harness.py
tools/semantic_logic/n3_validator/package-lock.json
tools/semantic_logic/n3_validator/package.json
tools/semantic_logic/n3_validator/sandbox_probe.mjs
```

No `src/llm_loop` file changes in P1-C.

## 3. Pinned backend identity

Qualification backend:

```text
backend_id          = eye-js-wasm
eyereasoner         = 21.1.18
swipl-wasm          = 7.0.10
EYE                 = EYE v11.24.5 (2026-08-23)
package-lock sha256 = 83d2ee38f112bea8929751a5a2c31dede5aec07312eb696ce660537d288c71be
```

The `eyereasoner` package integrity string is also checked against the tracked lock.

The local qualification installation lives only under ignored
`tools/semantic_logic/n3_validator/node_modules/`. It is not added to the Python
dependency graph or committed into Git.

A clean local rebuild was verified with:

```text
npm ci --ignore-scripts --no-audit --no-fund
```

Result:

```text
17 packages installed
package-lock hash unchanged
eyereasoner 21.1.18
swipl-wasm 7.0.10
```

## 4. Restricted execution profile

Every backend execution records and checks the fixed EYE argument shape:

```text
--nope
--quiet
--restricted
--tactic
limited-answer
<ANSWER_CAP>
--pass
./data.n3
```

The qualification sandbox is macOS Seatbelt with:

```text
deny network*
deny file-write*
deny process-fork
```

The sandbox probe independently verified:

```text
network denied               = true
host file write denied       = true
child process denied         = true
forbidden write materialized = false
```

The validator receives N3 data only through host stdin. The bridge writes it to the
Emscripten in-memory filesystem as `data.n3`; no arbitrary host input path is accepted.

## 5. Bounds and fail-closed behavior

Default frozen bounds:

```text
wall_timeout_ms          = 20000
max_input_bytes          = 1048576
max_output_bytes         = 1500000
answer_cap               = 4096
max_bridge_stdout_bytes  = 262144
max_bridge_stderr_bytes  = 131072
```

Qualification verified fail-closed behavior for:

- invalid bound values;
- input byte cap overflow;
- non-canonical N3;
- forbidden builtin markers;
- query surface use during P1-C;
- rulepack surface use during P1-C;
- package-lock tamper;
- backend/version mismatch checks;
- wall timeout;
- reasoner output cap;
- malformed or mismatched bridge receipts.

The 1 ms live timeout case fails with `wall_timeout`; the 1 KiB live reasoner output cap
case fails with `output_cap_exceeded`.

## 6. Canonical-input honesty

P1-C does not treat arbitrary N3 as trusted qualification input.

Before backend execution it requires the payload to reconstruct successfully through the
strict P1-B `load_canonical_n3` loader. This mechanically excludes, among other things:

- blank nodes;
- prefix abbreviations;
- arbitrary predicates/entities;
- rule syntax outside the frozen P1-B surface;
- duplicate or unsorted statements;
- mutated opaque-identity policy;
- structural/fingerprint drift.

The validator additionally rejects qualification-sensitive builtin markers before EYE is
invoked.

## 7. Frozen 15-case backend qualification

P1-C reuses the same P0/P1-A case builders. It does not create a second handwritten case
oracle.

All 15 S1-S5 frozen cases passed the actual pinned restricted EYE backend:

| Gate | Cases | Result |
|---|---:|---|
| S1 Grounding Closure | 3 | PASS |
| S2 C28 Source Conflict | 2 | PASS |
| S3 Predicate Honesty | 3 | PASS |
| S4 Version/Staleness | 4 | PASS |
| S5 Receipt Monotonicity/Single Dispatch | 3 | PASS |
| **Total** | **15** | **15/15 PASS** |

Across the 15 concrete P1-B N3 documents:

```text
input bytes total           = 2,731,339
reasoner output bytes total = 2,263,670
diagnostic bytes per PASS   = 0
```

The machine result records, per fixture:

- exact input SHA-256;
- exact input byte count;
- exact reasoner-output SHA-256;
- exact reasoner-output byte count;
- diagnostic SHA-256 / byte count;
- fixed EYE flags;
- gate/fixture identity.

Machine result:

```text
docs/SMC-SEMANTIC-LOGIC-P1C-RESULT-20260917.json
sha256 = 56464eee6e3607bb6921c1c568801ac2cbba9d922b47e702ef376a42d0dd1d3a
```

## 8. Determinism observation

A repeated live validation of the same frozen S3 canonical input produced the same:

```text
reasoner_output_sha256
diagnostic_sha256
```

Wall-clock duration is intentionally not part of the equality contract.

P1-C therefore records output identity by bytes/hash rather than by timing.

## 9. Focused and adjacent qualification

P1-C focused suite:

```text
24 / 24 PASS
```

Combined frozen semantic qualification:

```text
119 original Browser semantic oracle
+21 P1-A Typed IR
+26 P1-B canonical serialization
+24 P1-C restricted validator
=190 / 190 PASS
```

## 10. Static and whole-repository qualification

Exact implementation commit `59f66d67...`:

```text
Ruff new Python             PASS
Pyright new Python          0 errors / 0 warnings
py_compile                  PASS
Node syntax check           PASS
git diff --check            PASS
production consumer scan    0
```

Whole-tree security:

```text
1950 tracked files PASS
```

Formal full gate:

```text
scripts/ci_gate.sh          PASS
Ruff full                   PASS
env-pin                     590 test files / 0 undeclared
Pyright src                 0 errors / 0 warnings
tier0                       PASS
full xdist                  PASS
```

## 11. Authority audit

P1-C remains qualification-only:

```text
authority                    = shadow_only
production_consumed          = false
query_surface                = disabled_p1c
rulepack_surface             = disabled_p1c
negation_as_failure          = forbidden
custom_builtins              = forbidden
remote_imports               = forbidden
runtime permission authority = false
```

No production source imports the validator harness.

## 12. Non-effects

P1-C performed none of the following:

```text
provider-visible schema change
Browser/SMX/FileService production behavior change
mutation-authority change
runtime-authority change
semantic routing change
task-completion judgment
production package installation
push
deploy
service restart
8901/model restart or switch
```

## 13. Boundary after P1-C

P1-C is complete as a pinned, effects-disabled, bounded parser/reasoner validation plane.

P1-D remains a separate phase.

P1-D must compare all 15 cases across:

```text
Plane A = frozen Python canonical oracle
Plane B = Typed FactGraph relation set
Plane C = N3 parsed/entailed relation set
```

P1-D may add only the independently frozen narrow sentinel-query surface needed by the
architecture decision. It must not silently turn on the P2 Core Rule Engine, generic
rulepacks, negation-as-failure, production authority, or model-facing semantic routing.
