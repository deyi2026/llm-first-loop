# SMC Semantic Logic P0 — Read-only Rule Audit & Frozen Fixture Result

> Date: 2026-09-17
> Verdict: **P0 PASS — specification/frozen-oracle boundary only**
> Frozen code baseline: `main@19e253edfe4d3fcbeb268830b90d00fd273a6262`
> Production code changed: **no**
> Provider-visible surface changed: **no**
> Mutation/runtime authority changed: **no**
> P1 implementation: **NOT_STARTED**

## 1. Objective

Execute the P0 defined by `docs/PLAN-20260917-smc-semantic-logic-layer.md`:

1. inventory current SMC mechanical semantic invariants;
2. classify them as Core / Browser-specific / model-owned / runtime-owned;
3. identify repeated implementations;
4. freeze five initial Shadow Gates using existing deterministic oracles;
5. define an N3-compatible Fact / Rule / Derivation contract;
6. perform a paper adversarial review;
7. make no production behavioral change.

## 2. Baseline qualification

The repository root is intentionally not used as code identity because it is on another branch with pre-existing dirty state.

The audit baseline was frozen to the already deployed/qualified clean worktree:

```text
<repo>/.worktrees/deploy-main-19e253ed-20260917
HEAD 19e253edfe4d3fcbeb268830b90d00fd273a6262
```

Before using the root checkout for read-only inspection, all audited SMC source/test/profile paths were compared against `19e253ed`; the path-scoped Git diff was empty. Therefore the inspected semantics are byte-identical to the frozen main baseline for the audited surface.

## 3. Focused deterministic baseline

The following six existing canonical suites were run against exact `main@19e253ed` with `PYTHONPATH` bound to the exact worktree source:

| Suite | Tests |
|---|---:|
| `test_smc_browser_perception_v01.py` | 47 |
| `test_smc_browser_semantic_diff_v01.py` | 13 |
| `test_smc_browser_predicate_wait_v01.py` | 20 |
| `test_smc_browser_version_pressure_v01.py` | 14 |
| `test_smc_browser_action_v01.py` | 18 |
| `test_smc_browser_semantic_execute_v01.py` | 7 |
| **Total** | **119** |

Result:

```text
119 / 119 PASS
```

The repository's existing side-effect scanner emitted 41 non-blocking warnings about test provider URLs elsewhere in the repository; these warnings did not correspond to the focused SMC tests and did not fail the run.

## 4. Frozen source identity

P0 freezes the following baseline hashes for future shadow comparisons:

| Path | SHA256 |
|---|---|
| `src/llm_loop/browser/perception.py` | `ea412f300036451fea9bc448d887d7d9cbb47be89fcc40d1284989f9a9c3bf29` |
| `src/llm_loop/browser/predicate.py` | `44a1e395ac869d464e95584335de7fd362d80e0ede852faa13b7557855007343` |
| `src/llm_loop/browser/action.py` | `01404c0b919fa7caa51ea4a85f012cb4b1307a7a47cd2b11180bc272c17d0777` |
| `src/llm_loop/tools/builtin/browser_wait.py` | `cf8c4830c0233df80920f6ee9d2ea8a414fd8a7558bdfb1d421770248fcd77f8` |
| `src/llm_loop/tools/builtin/browser_semantic_execute.py` | `920f2f794b0f6a2ea8481fa2f7bc5e71091e8fa71353e62125d94f08557c1008` |
| `src/llm_loop/tools/builtin/smx_perceive.py` | `2c018b97d3518afcaee8ae485d1787115b862b9e2b6c885441ced533637e8198` |
| `src/llm_loop/workspace/file_service.py` | `ace0bbf33084bd9dc5c99e79fb40b7a5b3b518c90e6e3722de79970ff9424fd9` |
| `tests/fixtures/smc_browser_perception_v01.json` | `aadbf6077451824f96d9042bbe2c3cd2c6547dbc3b565bf682ba4765b0882dbb` |
| `tests/unit/test_smc_browser_perception_v01.py` | `1fed1653c1c7e8fd86aa0404132f457bc1123a1e13c949e7ac0829cc1d950571` |
| `tests/unit/test_smc_browser_semantic_diff_v01.py` | `ef9b30ca62d4c6649092e5e420490b29f5b73aa4c7bc04257a656c862516e628` |
| `tests/unit/test_smc_browser_predicate_wait_v01.py` | `211c0cf61f6335b1478dd1dbe024fe18bcc3fdabc427d772ebee7fe15a3ddf8f` |
| `tests/unit/test_smc_browser_version_pressure_v01.py` | `f51949e930d68cf63102aacd3ec6fb20358fd8507cdf362b977d3fad62419be1` |
| `tests/unit/test_smc_browser_action_v01.py` | `8a2507183578121f6bb5c8fe5882642b973a73cd5b36c8919360818ae4e27432` |
| `tests/unit/test_smc_browser_semantic_execute_v01.py` | `2835cb6419d360086eb6f92ae70eea42c15baa05c81646d9471ab231462975fe` |
| `docs/SMC-CONTRACT-v0.1.md` | `d6f489bd7357303c1948c5bef3510b25503eb9c4bcdbf2c43b1724331bb957e3` |
| `docs/SMC-BROWSER-PHASE1-PROFILE-v0.1.md` | `3ecf1a1c95dcffc4c7ed5e46c81b30d203ee1231089e6e8385a0712c67a64d78` |
| `docs/SMC-BROWSER-PHASE1-SCHEMA-v0.1.json` | `b688227b65fda26a26a67a642e98951e06ca39f89562e03c2cf8a1384d0bfb87` |

The machine manifest carries the same 17 hashes.

## 5. Rule inventory result

### 5.1 SMC Core candidates

The audit found eleven patterns that already exist across or above individual Browser operations:

1. **context-bound facts** — facts are scoped/versioned rather than timeless mutable state;
2. **source-qualified facts** — conflicting sensors are preserved;
3. **grounding exactness** — exact references cannot silently become nearest-current state;
4. **observation/projection separation** — capture gaps and display caps are not interchangeable;
5. **unknown != false** — missing observation is not negation;
6. **lower-bound witness reasoning** — positive witnesses can remain useful under partial coverage;
7. **comparability requirement** — diff/transition claims require compatible contexts;
8. **identity != similarity** — name/role similarity cannot establish continuity;
9. **explicit version precondition** — mutation-relevant state is compared against an explicit baseline;
10. **append-only revision** — cited execution truth is revised by append, not overwrite;
11. **proof provenance** — mechanical derivation should retain rule/input/grounding identity.

### 5.2 Browser-specific rules

These should remain Domain RulePack/Adapter facts:

- DOM and AX source semantics;
- page/document/frame hierarchy;
- Browser object kinds and properties;
- Browser verb contracts;
- click/fill/select/navigate/scroll physical semantics;
- page resource grounding;
- CDP locator/dispatch representation;
- Browser boundary-event detection.

### 5.3 Model-owned semantics

The audit confirmed that the following must remain outside RulePack authority:

- which target matters;
- which property/operator/value matters;
- whether waiting is useful;
- which action to choose;
- recovery strategy;
- relevance/importance;
- task completion.

### 5.4 Runtime-owned authority

The following cannot be minted by Semantic Logic:

- authentication/permission;
- session/run ownership;
- resource/effect mutation authority;
- locks and reservations;
- action-id single-dispatch reservation;
- physical dispatch;
- atomic file replacement;
- durable/fsync receipt append.

## 6. Duplicate implementation result

P0 found five meaningful duplication families.

### D1 — exact object-reference resolution

Equivalent `GroundingRef -> exact hydrate -> id/scope` logic appears in multiple Browser wait and semantic-execute code paths.

This is the strongest immediate candidate for one shared semantic reference resolver in a later implementation phase.

### D2 — Predicate identity compilation

Fixed `schema/domain/scope_ref/target` relationships are assembled repeatedly while the model actually owns only the semantic condition.

### D3 — action fixed fields

Verb→args/version-scope/fixed action metadata exists across mutation contract, semantic compiler, profile/schema and provider guidance.

### D4 — completeness/scope/diff patterns

Browser and SMX independently implement comparable completeness, scope and snapshot-diff concepts.

### D5 — immutable version-precondition pattern

Browser expected-version and FileService expected-snapshot are physically different but share the abstract relation:

```text
immutable baseline + current observation
=> match | stale/conflict | indeterminate/invalid
```

P0 does not refactor any of these duplicates; it only freezes them as future semantic-logic candidates.

## 7. Cross-domain evidence

The architecture is not justified solely by Browser.

### SMX

Current SMX already exposes an additive SMC projection with:

- scope relation;
- observation completeness;
- projection completeness;
- snapshot-pair diff;
- Predicate result;
- ActionReceipt/grounding facts.

### FileService

Current FileService independently enforces:

- exact immutable snapshot reference;
- workspace/path scope;
- exact-byte version comparison;
- version conflict;
- stable lock;
- runtime mutation authority;
- no task-semantic judgment.

Conclusion: scope, version/context, completeness and provenance are justified as SMC Core concepts, while their physical realization remains domain-specific.

## 8. Frozen Shadow Gates

The machine fixture manifest freezes five gates:

| Gate | Purpose | Cases |
|---|---|---:|
| S1 | Grounding Closure | 3 |
| S2 | C28 Source Conflict | 2 |
| S3 | Predicate Honesty | 3 |
| S4 | Version/Stale | 4 |
| S5 | Receipt Monotonicity/Single Dispatch | 3 |

Total frozen cases: **15**.

Each case references existing exact pytest oracle nodes rather than creating a second independent semantic truth source.

## 9. Opaque identity qualification rule

One important P0 correction to the initial planning language is frozen here:

> Existing Browser semantic behavior is deterministic, but the complete serialized output is not byte-deterministic because snapshot IDs, opaque scope/GroundingRefs, runtime nonce and timestamps intentionally vary by run.

Therefore future equivalence uses one of three explicit modes:

```text
byte_exact
closed_field_exact
opaque_identity_isomorphic
```

`opaque_identity_isomorphic` permits only a relation-preserving bijection over fields explicitly declared opaque by the fixture.

It does **not** permit normalization of:

- source values;
- conflict status;
- reason codes;
- completeness;
- version relation;
- operation/authority class;
- receipt order/status;
- retry facts;
- semantic property/operator/value.

P1 must either provide a deterministic identity/time harness or implement this strict equivalence relation. Generic JSON normalization is not acceptable.

## 10. Machine schema validation

Generated P0 schema:

`docs/SMC-SEMANTIC-LOGIC-P0-SCHEMA-v0.1.json`

Generated fixture manifest:

`docs/SMC-SEMANTIC-LOGIC-P0-FROZEN-FIXTURES-v0.1.json`

Validation evidence:

```text
system python jsonschema 4.26.0
Draft202012Validator.check_schema -> PASS
fixture manifest validate -> PASS
gates = S1:3, S2:2, S3:3, S4:4, S5:3
source_hashes = 17
```

The project `.venv` does not contain the optional `jsonschema` package. No dependency was installed; the already-present system `jsonschema 4.26.0` was used only for read-only schema validation.

## 11. Adversarial paper review

P0 performed a contract-level review against the following failure classes.

| Attack / ambiguity | P0 contract ruling | Status |
|---|---|---|
| absent item collapses to false | negative closure requires sufficient relevant coverage | PASS |
| DOM/AX conflict silently prefers one source | unresolved conflict retains both grounded observations | PASS |
| stale/expired ref silently refreshes | exact GroundingRef remains version/retention bound | PASS |
| replacement rebinds by same name | identity basis/generation, not similarity | PASS |
| facts from two snapshots mixed as one context | every fact/derivation carries explicit context refs | PASS |
| projection truncation treated as sensor gap | observation and projection completeness are separate | PASS |
| hydrate repairs physical blind spot | forbidden; hydration cannot improve original observation completeness | PASS |
| model-authored rule grants itself authority | model rules remain `candidate_only` | PASS |
| semantic rule mints permission/effect authority | runtime authority is non-mintable by Logic | PASS |
| recursive rule closure grows without bound | future implementation must use bounded/cycle-safe closed RulePack; cannot pass P2 otherwise | PASS at spec level |
| receipt `ok` means task complete | task completion explicitly model-owned/forbidden Rule output | PASS |
| ambiguous transport automatically replays mutation | no-auto-retry remains Runtime invariant | PASS |
| provenance requires secret plaintext | privacy-safe hashed/ref provenance allowed; gaps remain explicit | PASS |
| Browser physical semantics leak into File domain | core abstract rule separated from domain physical semantics | PASS |

No unresolved **contract-level** authority gap remains for beginning a shadow implementation later.

This does not claim implementation conformance because no Semantic Logic engine exists yet.

## 12. P0 deliverables

Planning baseline:

- `docs/PLAN-20260917-smc-semantic-logic-layer.md`

P0 outputs:

- `docs/SMC-SEMANTIC-LOGIC-v0.1.md`
- `docs/SMC-RULE-AUTHORITY-v0.1.md`
- `docs/SMC-FACT-PROVENANCE-v0.1.md`
- `docs/SMC-SEMANTIC-LOGIC-P0-SCHEMA-v0.1.json`
- `docs/SMC-SEMANTIC-LOGIC-P0-FROZEN-FIXTURES-v0.1.json`
- `docs/SMC-SEMANTIC-LOGIC-P0-AUDIT-20260917.md`

## 13. P0 PASS criteria

| Requirement | Result |
|---|---|
| exact baseline frozen | PASS — `19e253ed...` |
| current canonical deterministic suite healthy | PASS — 119/119 |
| mechanical rule inventory complete for audited surface | PASS |
| Core / Browser / Model / Runtime ownership split | PASS |
| duplicate implementation map | PASS |
| Fact/Context/Provenance contract | PASS |
| Rule authority/lifecycle contract | PASS |
| Derivation/proof contract | PASS |
| closed machine schema | PASS |
| schema validates under Draft 2020-12 validator | PASS |
| five frozen shadow gates | PASS — 15 cases |
| paper adversarial authority review | PASS |
| production code change | NONE |
| provider-visible schema/tool change | NONE |
| mutation authority change | NONE |
| P1 implementation | NOT_STARTED |

## 14. Final P0 ruling

**P0 PASS.**

The audit supports introducing a first-class Semantic Logic Layer, but only as a shadow system first.

The key architectural result is:

```text
LLM owns semantic choice
Semantic Logic owns deterministic semantic closure
Adapter owns physical grounding and actuation primitives
Runtime owns hard authority, idempotency and durable execution boundaries
```

The initial implementation target should not be “N3 everywhere”. The next phase should compare a bounded typed IR, a direct N3 reasoner, and a hybrid typed-IR/N3-validation design against these frozen 15 cases before selecting a runtime dependency or granting any production authority.

P0 ends here. P1 requires a separate explicit owner instruction.
