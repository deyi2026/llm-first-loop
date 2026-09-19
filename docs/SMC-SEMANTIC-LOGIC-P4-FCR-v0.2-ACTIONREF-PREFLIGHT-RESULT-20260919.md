# SMC Semantic Logic P4-FCR v0.2 — ActionRef Preflight Result

> Date: 2026-09-19
> Status: **QUALIFIED_DETERMINISTIC_PREFLIGHT_ONLY / STOP BEFORE REAL MODEL**
> Exact implementation candidate: **eae7638c83503472918927f93df49a26469200a8**
> Protocol commit: **d2945cfc5459cf69ae963b1b71a13976fdc6de75**
> Immutable v0.1 negative parent: **52d5e78e650e1693db3453285febf36e8ab9cb68**

## 1. Verdict

P4-FCR v0.2 has completed deterministic qualification and a real-environment
preflight without issuing any model request.

The proposed treatment is mechanically coherent:

- Arm A keeps the v0.1 full GroundingRef control surface.
- Arm B keeps the same five typed semantic verbs but replaces the model-visible
  full GroundingRef with a short opaque ActionRef.
- The qualification compiler performs exact ActionRef lookup and hydrates only
  the already-bound GroundingRef before delegating to the existing Browser
  semantic compiler.
- No search, ranking, fuzzy match, rebind, refresh, successor substitution,
  retry, semantic argument rewrite, Browser execution, or completion judgment
  is added.

Because this changes the provider-visible Arm-B identity representation, it is
a **material protocol change**. Per the frozen protocol, the experiment stops
here for a human checkpoint before the first real v0.2 model row.

## 2. Causal basis

P4-FCR v0.1 remains immutable and NOT_QUALIFIED.

Its four Arm-B mechanical failures were all select declarations in which the
provider-visible first declaration changed the exact grounding scheme from
grounding:// to ground:// for the same el_333 target.

The v0.1 scorer observed those raw bytes without normalization. P4-D merely
forwarded the declared ref to canonical target_ref.

Therefore v0.2 changes only the model-visible mechanical identity burden rather
than Browser runtime semantics.

## 3. Frozen v0.2 surface

The core experiment remains five task families x four repeats x two arms:

**40 rows**

with the exact v0.1 task rotation and A/B ordering.

Arm-B target handles:

| Task | ActionRef |
|---|---|
| navigate | ar_5f8c2a |
| click | ar_a17d93 |
| fill | ar_c42e11 |
| select | ar_7b31f0 |
| scroll | ar_d9054c |

The handles use the same short lexical shape and contain no semantic verb.

Each pair receives byte-identical user text containing both the exact
GroundingRef and its bound ActionRef. The tool schema, not arm-specific prompt
text, determines which representation is declared.

Frozen semantic plan SHA-256:

**62a4e18477d794140c46577efa32f33a4ef04da1659aa3a448499b5b74b54ad4**

## 4. Deterministic ActionRef qualification

The v0.2 focused suite proves:

- all five typed operations hydrate back to the exact GroundingRef and compile
  byte-semantically equal to Arm A;
- static frozen bindings pass integrity verification;
- unknown handle rejects;
- wrong session rejects;
- wrong authority rejects;
- stale observed version rejects;
- expired retention rejects;
- tampered record rejects;
- object/resource kind mismatch rejects;
- old object_ref shape rejects;
- malformed typed arguments reject;
- same exact ActionRef request produces the same canonical action and action_id;
- all rejection paths perform zero Browser dispatch.

Raw FCR scoring remains pre-hydration. A wrong ActionRef or a full GroundingRef
placed in the ActionRef field is mechanically invalid and remains visible as a
targeted P4-X06 error.

## 5. Focused and adjacent qualification

Exact committed-state qualification on candidate
eae7638c83503472918927f93df49a26469200a8:

| Suite | Tests | Result |
|---|---:|---|
| P4-FCR v0.2 ActionRef | 25 | PASS |
| P4-FCR v0.1 preflight adjacency | 7 | PASS |
| P4-D typed compiler adjacency | 19 | PASS |
| **Total** | **51** | **51/51 PASS** |

Additional checks:

- Ruff: PASS
- Ruff format: PASS
- Pyright: **0 errors / 0 warnings**
- protocol JSON parse: PASS
- plan JSON parse: PASS
- git diff check: PASS
- commit security scan: PASS
- production src changes from the v0.1 negative parent: **0**

## 6. Qualification backend restoration

The first full-CI run on the fresh worktree failed in the pre-existing N3 shadow
test family because the gitignored restricted-EYE node_modules were absent with
the exact error pinned_backend_not_installed.

Repository qualification documentation records this exact fresh-worktree
condition and the approved recovery.

The backend was restored only from the tracked lock using npm ci with scripts
disabled.

Verified identity:

- eyereasoner: **21.1.18**
- swipl-wasm: **7.0.10**
- EYE: **v11.24.5 (2026-08-23)**
- Node: **v24.18.0**
- package-lock SHA-256:
  **83d2ee38f112bea8929751a5a2c31dede5aec07312eb696ce660537d288c71be**

The restore did not change tracked Git state.

## 7. Full repository CI

After restoring the exact pinned qualification backend, full CI was rerun from
scratch.

Final exit status: **0**

Observed:

- all-repo Ruff: PASS
- env-pin gate: **607 test files / 0 undeclared**
- src Pyright: **0 errors / 0 warnings**
- tier0: PASS
- full xdist gate: PASS under the repository's D-B2-09 discipline

One xdist distribution false-red appeared in tests/unit/test_schedule_wake.py.
The built-in serial single-file recheck passed, so the repository correctly
classified it as non-blocking distribution noise.

The existing 41 audit-test-side-effects findings remained non-blocking warnings.

## 8. Real environment preflight

Preflight was run against the existing single Ornith service only.

It did not start, stop, restart, or switch any model.

Verified model-server facts:

- model basename: **Ornith-1.5-35B-A3B-MLX**
- prompt concurrency = 1
- decode concurrency = 1
- max tokens = 16000
- server command SHA-256:
  **2bee17c3fb687fb9224f0f72cac6738c607515a3ba92b90ae867995dd7b85fcf**

Preflight result:

| Fact | Value |
|---|---:|
| plan rows | 40 |
| model requests | **0** |
| tool execution total | **0** |
| Browser runtime used | **false** |
| measured row dirs | 0 |
| results present | false |
| qualification gate present | false |
| shared A/B surface | identical shared subset |

Surface hashes:

- Arm A wire SHA-256:
  **fe712ab451c3db44d043be4dc098e6f83c0a22701dc3dee1b32a606d893a42bf**
- Arm B wire SHA-256:
  **18c5b1bd97f19cb2329871f644f48330d49d682d12f3e0fb65442afb95df1040**

External preflight artifact hashes:

| Artifact | SHA-256 |
|---|---|
| plan.json | 55133970a6e36c586b37de2c11641c3777b38d814990f0abbcec96633a4b37dc |
| execution-manifest.json | 13563c964b315ac1a82a5422c3658f47a5c16d8ce479de54844c4ed666470732 |
| preflight.json | 09d66f20cdacf48b5aa4366b5120f115f9cac22e8672367415f0d3c6a46e00a1 |

## 9. Frozen evidence

Qualification evidence is stored at:

evals/smc_semantic_logic_p4_fcr_v02/results/PREFLIGHT-v0.2-20260919/EVIDENCE.json

Evidence SHA-256:

**7e07918564c0945453910bbcf55a7cab25c10d9e2ec7df8fd3297b6378294bcb**

The evidence binds the candidate commit, protocol commit, v0.1 negative parent,
P4-D base, P1/P1.1 remote anchors, source hashes, surface hashes, deterministic
test gates, full CI facts, qualification backend identity, and preflight facts.

## 10. Non-claims

This phase does **not** prove:

- that Ornith will copy the short ActionRef correctly;
- that Arm B reaches 20/20 mechanical validity;
- that targeted P4-X01/X02/X06/X07 errors reach zero;
- that P4-FCR v0.2 is QUALIFIED;
- that ActionRef is ready for production Browser wiring;
- that P4-LIVE is qualified.

No real v0.2 model row has run.

## 11. Human checkpoint

The deterministic architecture and environment gates are complete.

The next action, if authorized, is a fresh serial 40-row declaration-only FCR
run using the already frozen plan:

- no reruns;
- no reordering;
- no Browser tool execution;
- no hydration during scoring;
- no retry;
- no normalization;
- offline scoring only after the frozen run completes.

Qualification remains:

- Arm B structural = 20/20;
- Arm B mechanical = 20/20;
- P4-X01/P4-X02/P4-X06/P4-X07 total = 0;
- all integrity/safety invariants pass.

Until that explicit authorization, the experiment remains stopped before the
first real model request.
