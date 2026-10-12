# Learning Method semantic integration qualification

Date: 2026-09-26

## Status

**Isolated qualification: PASS. Production activation: NOT YET AUTHORIZED.**

This work starts from generation-115 base
`e04172f2abf31c18db1cc664a2c0894fd54e7375`. It adds a real consumer for
`SEMANTIC_METHOD_ENABLED` in the dedicated Learning runtime. Canonical production
configuration was not changed and no production service was restarted during this phase.

## Problem

Before this change, Learning Reflection received only `existing_methods`, a flat list of at
most 30 active/qualified Method briefs. `SEMANTIC_METHOD_ENABLED` could build and warm a
Method semantic retriever, but Learning never consumed that retriever. Turning the flag on
would therefore have been configuration-only activation rather than real feature wiring.

The current Method corpus also makes an unrestricted top-k unsafe for Learning reuse:
qualification found 536 Method records, of which 524 were `candidate` and only seven were
`active`. In the unrestricted semantic ranking, relevant active Methods landed as low as
rank 28 because candidate records occupied the top results.

## Qualified design

Learning now receives an optional `method_discovery` callback from `factory.py` only when
`semantic_method_enabled=true` for the Learning runtime.

The consumer contract is intentionally narrow:

- the semantic candidate authority is only `active` / `qualified` Methods;
- generic `search_records(kind=method)` keeps its existing broader lifecycle visibility;
- the query is mechanically built from durable model-visible episode material, trigger
  facts and final outcome, capped at 1,200 characters and never reads hidden reasoning;
- at most six related Methods are exposed to Reflection;
- related Methods are advisory candidates with `task_applicability=not_evaluated`;
- retrieval rank never decides applicability or duplication by itself;
- the existing 30-entry `existing_methods` brief list remains as the compatibility/global
  dedup fallback;
- discovery errors are fail-open and carry mechanical diagnostics;
- API embedding failure preserves the existing whole-space Hash fallback, with explicit
  `primary_to_hash` provenance;
- Learning remains P3 background work and foreground preemption semantics are unchanged.

Learning startup warming is also scoped to the active/qualified view. This avoids warming
hundreds of unqualified candidates solely for Reflection reuse/dedup.

## Evidence

### Canonical Method tool gate

Artifact: `evals/retrieval_ab/learning-method-semantic-canonical-tool-20260926.json`.

- seven current active Method families: 7/7 target rank #1;
- 7/7 semantic-effective;
- zero fallback and zero missing vectors;
- local embedding sidecar error delta 0 and queue idle afterward;
- active-only startup build remained sub-second in the measured isolated run.

The earlier unrestricted probe demonstrated why status filtering is required: current
`method-root-cause` was semantic rank 8 and `method-repo-api-discovery` rank 28 in the full
536-record pool, while each was rank #1 within the active subset.

### Real-model scale A/B

Artifact: `evals/retrieval_ab/learning-method-semantic-model-ab-20260926.json`.

An isolated corpus placed the matching active Method beyond the legacy 30-brief window.
With the current GLM provider/model:

- OFF: 0/3 explicit duplicate recognition and 2/3 runs minted a new candidate;
- ON: 3/3 recognized the existing target as the duplicate and 0/3 minted a candidate;
- ON rows were all semantic-effective with zero missing/hydration failures;
- embedding error delta remained 0 and queue returned idle.

This is the primary benefit gate: semantic discovery prevents redundant Method growth when
the flat brief budget hides the relevant reusable Method.

### Canonical model non-regression

Artifact: `evals/retrieval_ab/learning-method-semantic-canonical-model-20260926.json`.

Three current active families were evaluated against a copy of the canonical Method store.
Both OFF and ON produced zero new candidates. ON was semantic-effective for all three with
zero fallback/missing/hydration failures. Explicit duplicate-ref wording varied between
model runs, so that wording is not treated as a benefit KPI; duplicate candidate growth is.

### Embedding fault gate

Artifact: `evals/retrieval_ab/learning-method-semantic-fault-20260926.json`.

With the primary API embedding endpoint unavailable, startup reported unresolved primary
vectors without blocking Learning. Discovery switched to the existing Hash semantic space,
kept the active target at rank #1, and reported `semantic_fallback_reason=primary_to_hash`
plus the primary transport error. The fallback is therefore visible rather than silently
reported as a healthy primary semantic request.

### LearningJournal end-to-end gate

Artifact: `evals/retrieval_ab/learning-method-semantic-journal-e2e-20260926.json`.

An isolated real Learning job exercised:

`LearningJournal.enqueue -> LearningPlane._try_execute -> Reflection -> journal terminal`.

The matching Method was outside the legacy 30-brief window, semantic discovery ranked it
#1, the job completed one attempt to terminal `none`, and Method count stayed 49 -> 49.
The local embedding sidecar recorded zero errors and returned idle.

### Regression and static gates

- focused/adjacent set: 65/65 PASS;
- broad Learning/Method/foreground/provider-settlement/Web-stream adjacency: 159/159 PASS;
- one compatibility regression found during the broad run was fixed by treating the new
  diagnostics field as optional on legacy/test outcome objects;
- Ruff PASS;
- modified-source compileall PASS;
- `git diff --check` PASS;
- Pyright introduced zero new errors; the three reported `factory.py` hook return-type
  errors are identical to the generation-115 parent baseline;
- full tracked-tree security scan: 3,254 files PASS.

Aggregate evidence:
`evals/retrieval_ab/learning-method-semantic-qualification-20260926.json`.

## Production boundary

This qualification deliberately does **not** change canonical `runtime.toml` and does not
restart Learning, Web, or Feishu. Production Learning therefore remains Method semantic OFF
until a separate owner checkpoint.

If production activation is authorized later, the next phase should be single-service and
single-variable:

1. publish the clean qualified candidate through managed service authority;
2. persist only a Learning-specific Method semantic override, leaving Archive/Docs/
   Experience OFF;
3. dry-run resolver/manifest/config-hash and knowledge binding;
4. restart **Learning only** through `service_control` after its idle gate passes;
5. verify the new Learning manifest reports Memory=1 / Method=1 / Archive=Docs=Experience=0
   with correct per-service provenance;
6. rerun canonical Method tool/model + journal smoke and Memory compatibility;
7. verify Web and Feishu PIDs/health are unchanged, local embedding errors remain zero and
   queue is idle;
8. rollback only the Learning override if any stop condition fires.
