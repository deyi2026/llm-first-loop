---
method_id: staging-smoke-unexercised-input-paths-before-expensive-runs-1c09b39bfca9
name: staging-smoke-unexercised-input-paths-before-expensive-runs
description: Before spending model budget on a runner whose load paths were exercised only on a subset of inputs, mechanically smoke every newly exercised input at zero token cost: workspace assembly, seed write + read-back via the engine's own access path, scorer dry-run. Treat all-arms-symmetric failure on a new input as suspected plumbing until mechanism signals and a trajectory confirm a task-level cause. In this episode two latent loader bugs surfaced only via crashed/mis-scored rows and forced repeated re-freezes; a per-task staging smoke would have caught both for free.
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:76:decb513e3b563b0edc36
evidence_refs: learning:learn:2cc12e0e3b77
created_at: 2026-09-20T22:11:21.582698+00:00
updated_at: 2026-09-20T22:11:21.582698+00:00
---
## Trigger
About to spend expensive (model/API) runs on an eval or driver whose assembly/seeding paths were previously exercised on only a subset of the inputs now in the plan (e.g., pilots, freeze rows, and tooling docstrings only ever covered t1-t3 while the plan adds never-run inputs).

## Discriminator
Concrete evidence that load-path coverage is partial: prior run rows, freeze manifests, and tool docstrings list only a subset of inputs as ever executed or supported, while the current plan includes never-run inputs whose assembly/seed code paths have zero prior exercise.

## Short path
- Read the authoritative annotation/defect record plus the files it names; apply known fixes and restore broken prerequisites (e.g., deleted deploy tree). Unknown resolved: are the recorded defects closed on current code?
- From run history and tool docstrings, list which inputs any prior execution actually exercised. Unknown resolved: which inputs have unverified assembly/seed plumbing?
- For each never-exercised input, run a zero-token staging smoke on the frozen baseline: copy/assemble workspace, write seed state, read it back through the engine's own access path, dry-run the scorer. Unknown resolved: does the load path work at all (catches unconditional-copytree crashes and seed-written-where-engine-never-reads mismatches)?
- Fix what the smoke surfaces, then freeze once. Unknown resolved: is the frozen baseline clean for every plan input?
- Run the expensive rows; for any symmetric all-arm failure on a new input, check mechanism signals (e.g., feature-activation counters) and one trajectory to classify harness bug vs genuine task result before recording conclusions. Unknown resolved: is the failure a task property?

## Stop conditions
- Every input in the run plan has passed the staging smoke against the exact frozen code baseline.
- Every all-arms-symmetric failure has an evidence-backed classification (plumbing defect vs genuine task result) before it feeds any discriminability conclusion.

## Verification
- Smoke input coverage equals plan coverage (100% of inputs, including never-run ones) and executes against the frozen manifest's code hash.
- Seed read-back through the engine's real access path returns the seeded content, proving write path equals read path.
- Each reward=0.0-on-all-arms row has a recorded root cause (with mechanism-signal or trajectory evidence) before its result is used in conclusions.

## Counterexamples
- New inputs share an identical, already-exercised loading path (same layout, same seeding) — the smoke is redundant; run directly.
- Symmetric failure arrives with active mechanism signals (feature triggered, arms diverge in trajectory/cost) — it is a genuine task result, not plumbing.
- Per-input runs are cheap and mechanical with no model cost — a separate smoke layer is pure overhead; just run the real thing.
