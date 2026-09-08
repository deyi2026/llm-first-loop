# Method Learning v1

## Purpose

Method Learning lets LFL accumulate reusable **ways of narrowing and acting on a problem** without turning those methods into a second programmatic decision system.

The lifecycle is:

`episode/evidence -> self-distill -> candidate -> reuse/qualification -> qualified -> active -> revise/hold/invalidate/retire`

A Method is distinct from:

- **Evidence**: exact task/run facts;
- **Experience**: what happened, why, and what fixed it;
- **Rule**: durable authority/constraint;
- **Skill**: an executable or loadable workflow surface;
- **Method**: a transferable discriminator + shorter evidence-driven action path.

## Authority boundary

Program-owned, mechanical facts:

- Method identity/content hash/version path;
- lifecycle status and explicit transition receipts;
- source episode/evidence/model/teacher provenance;
- exact bytes of Method assets;
- whether an exact Method was hydrated in a run;
- rounds/tool-call/status/outcome telemetry;
- qualification records explicitly submitted by model/owner;
- candidate write isolation and no-overwrite behavior.

Model/owner-owned semantic judgments:

- whether an episode contains a reusable Method;
- Method abstraction and counterexamples;
- current task applicability;
- whether a hydrated Method was actually applied;
- whether qualification evidence is persuasive enough to promote, revise, hold, or invalidate.

The program must not select a Method because it thinks the Method is semantically relevant, and must not infer `application_proven=true` from a load.

## Storage boundary

Two physical tiers deliberately prevent autonomous learning from dirtying or leaking into the public source tree:

- `methods/`: reviewed tracked seed/canonical/teacher assets;
- `data/methods/` (default `METHODS_DIR`): runtime-learned candidates and lifecycle state.

`METHOD_SEED_DIR` defaults to `./methods`. Search merges both tiers. Runtime candidates win exact-id collisions but never overwrite seed bytes.

## Retrieval and progressive disclosure

`search_records(kind=method)` is the single discovery entrypoint.

- ordinary query -> compact Method cards with `method:<id>`, lifecycle status, description, content hash and `task_applicability=not_evaluated`;
- exact `query=method:<id>` -> full Method body + qualification records.

No Method/Teacher/Candidate is automatically injected into the universal prompt. The model chooses whether to search/hydrate.

## Seed asset roles

The v1 seed set preserves all existing Method learning work:

- active/canonical: root-cause, repo-api-discovery, ab-experiment;
- active meta-method: method-self-distill;
- hold: web-source-diagnosis (existing negative-transfer evidence; not falsely promoted);
- teacher: self-distill root-cause / repo-api / A-B exemplars;
- candidate: hydrate-trace, A-B validity/trigger confound, current-callsite-refresh, relative-clock-never-state.

Teacher and Candidate are first-class Method assets, not hidden benchmark leftovers.

## Candidate creation

`method_manage(action=save_candidate)` persists model-authored Method content. It:

- requires explicit name/description/body;
- records runtime-derived source model/session provenance; Teacher provenance is derived only when Teacher fallback actually runs; model-supplied evidence/parent refs remain declarations, not runtime identity;
- derives a deterministic content-hash id;
- never overwrites an existing candidate;
- always creates `status=candidate`;
- never edits the public seed directory.

The candidate body should contain trigger/discriminator/short path/branches/stop/verification/counterexamples and must not contain hidden chain-of-thought.

## Qualification and lifecycle

`method_manage(action=record_qualification)` appends an independent qualification receipt with separate:

- verdict;
- mechanism;
- task benefit;
- promotion;
- task/evidence refs.

`method_manage(action=refine)` controls explicit lifecycle transitions. Mechanical fences include:

- `candidate -> active` is forbidden;
- `candidate -> qualified` requires at least one qualification receipt with `promotion=pass` and a task ref; a `promotion=pass` task ref cannot equal the candidate source episode ref;
- Teacher assets are immutable as teachers; a learned derivative must be a new Candidate.

These fences mechanically prevent the source episode itself from authorizing promotion and prevent same-episode self-distillation from silently becoming active policy. They do **not** claim the program can judge qualification quality.

## Post-run self-distillation

`METHOD_REFLECTION_MODE=off|auto`, default `off`.

When `auto` is enabled, reflection occurs only after the user-visible final answer is already determined. It is isolated and fail-open: reflection failure cannot rewrite or fail the task.

Mechanical friction trigger can use only observable facts such as:

- rounds;
- number of tool calls;
- tool failures;
- exact duplicate tool name+argument calls;
- stagnation/max-iteration terminal reason.

The reflection projection excludes `reasoning_content` and provider-private replay state. It sends bounded user/assistant/tool visible content plus tool/action facts to the same routed model.

First pass uses `method-self-distill`. If output is structurally invalid, at most one second pass may include Teacher exemplars. Teacher fallback teaches the abstraction procedure, not the current answer.

Valid output is either:

- `decision=none` (no reusable Method); or
- a structured Candidate, which is written only to runtime `data/methods/`.

## Usage measurement

When a run exact-hydrates `method:<id>` through `search_records`, LFL emits `method.usage_observed` with:

- method refs;
- run end reason;
- rounds/tool-call count;
- model identity;
- `application_proven=false`.

This intentionally avoids claiming that loading means applying. Qualification remains explicit through independent A/B/counterexample evidence.

The post-run reflection emits `method.reflection` with attempted/triggered/saved-ref/teacher-fallback/reason. These are prompt-neutral durable facts.

## Privacy and chain-of-thought

Method Learning must never request, persist, reconstruct, or replay hidden chain-of-thought. Reflection sees only observable episode/action/evidence facts.

Runtime-learned candidates are local data by default. A candidate is not publication-ready merely because it exists or becomes active locally. Moving it into tracked `methods/` requires a separate privacy/content review.

## Non-goals

Method Learning v1 does not:

- automatically inject the “best” Method;
- programmatically decide semantic applicability;
- treat one successful task as promotion;
- turn Method cards into mandatory workflows;
- modify StateBraid/cache admission based on Method semantics;
- change the universal prompt.
