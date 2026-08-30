# R8.8 Prompt Eligibility Blocker Closure

Status: **PASS / behavior-canary eligibility gate READY; behavior canary NOT STARTED**

## Scope

R8.8 closes the seven non-tool blockers left after R8.7 without entering model-profile behavior canary or R9. The owner rule remains:

> **resolved is retrievable, not injectable**

The hard order is unchanged: lifecycle eligibility → retrieval/representation → model profile → injection budget → provider wire.

## Closed blockers

1. **Legacy resolved episodes — evidence-gated migration.** Pre-R8.5 history is not guessed resolved. `episode_history` correlates a legacy assistant `message.appended` with the following durable `run.end`; migration requires `reason=completed`, `truncated=false`, matching `answer_preview`, exact saved content, and exactly one candidate in that run segment. Missing/corrupt/ambiguous evidence leaves the episode provider-visible. A read-only census over current session/event storage found 182 legacy completed-model answers across 19 sessions; 136 (74.7%) were provable, while 46 remained deliberately unretired. Migration itself is lazy on next ingress and still uses EpisodeStore durable-write-before-ref-stamp.
2. **`model_switch_notice` — observability only.** Model switches no longer copy recent user/assistant text or emit a program `continue` command. A transition records only `model.switch` action observability.
3. **Evidence Recovery Manifest — no automatic prompt projection.** `build` no longer appends the recovery index each request, so it no longer bypasses R2. Ledger, ManifestProjector, resolver reuse and evidence tools remain. `list_evidence(scope="recovery")` explicitly exposes the same bounded prioritized manifest on demand; `scope="recent"` preserves the old recent-list behavior.
4. **`memory_snapshot` — current-turn identity gate.** A persisted snapshot is automatically visible only when `metadata.turn_ref` exactly matches the active human turn. Older, unbound legacy and resolved snapshots are excluded both from flat provider history and Cognitive packet input. Durable memory retrieval remains unchanged.
5. **Local behavior patch — removed.** The per-build local-provider command-shaped autonomy/search hint is gone. Evaluation hints do not acquire production prompt authority.
6. **Unknown dynamic producer — deny by default.** Prompt eligibility now has an explicit dynamic-producer allowlist before semantic label/profile/budget. Unknown/unattributed producers are dropped with prompt-eligibility telemetry; `infer_layer`'s compatibility STATUS fallback is not an eligibility grant.
7. **Round exhaustion — metadata lifecycle + persisted consume.** Consumption uses `injection_kind=round_exhaustion_decision`, not wrapped visible text, and occurs before `session.save`, preventing reload resurrection.

## Recovery and non-loss properties

- Resolved episode content remains in durable EpisodeStore and is searchable/hydratable by `search_records(kind=episode)`.
- Old memory remains stored/searchable; only automatic prompt eligibility changes.
- Evidence remains durable and can be discovered without a remembered keyword/path via `list_evidence(scope="recovery")`; exact content remains retrievable with `read_evidence`.
- No historical session is bulk-mutated by R8.8. Legacy retirement happens only when durable evidence proves the boundary on a future ingress.

## Focused/adjacent verification

Current R8.8 focused and adjacent suite: **112/112 PASS**, covering prompt eligibility, model-switch, exhaustion, episode migration, memory turn isolation/reference projection, Cognitive shadow, injection label/budget/focus, and Evidence Phase4/5/7. Evidence Phase4/5/7 specifically passes **31/31** with automatic Manifest absent from provider prompts and on-demand recovery preserved.

Detached-clean fixed-point on implementation commit `b6050d3` passed: focused/adjacent 112/112, context-warning isolation 2/2, touched pyright 0/0, py_compile PASS, R0-1~R0-4 PASS, frozen R0 hash byte-identical, and clean status before/after verification.

## Canary boundary

`eligibility/matrix.json` now has zero entries in `canary_blockers`, `behavior_canary_allowed=true`, and `behavior_canary_gate_state=READY`. This means only that the Prompt Eligibility prerequisite is satisfied. **R8 model-profile behavior canary and R9 are not started by R8.8.**
