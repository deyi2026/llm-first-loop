# LFL Convergence + Disposition Gate — 2026-09-10

> **Status: PROPOSED CONVERGENCE SoT / docs-only**
> **Qualified semantic anchor:** `feature/resource-governor-rg3e-authoritative-adapters-20260910@cf5e6fb`
> **Convergence target:** the qualified anchor **plus only individually reviewed and requalified independent deltas**; no unqualified branch is auto-merged.
> **Official repository baseline:** `lfl/main@d59169f`
> **Paired mechanical replay matrix:** `docs/analysis/CONVERGENCE-DISPOSITION-20260910.json`
> **Scope of this document:** convergence, ownership, measurement and governance wiring only. It does **not** merge branches, change production runtime, enable RG-3F, start Reasoning Lab, or modify services.

---

## 0. Executive ruling

LFL has reached an asymmetric state:

1. **Mechanical substrate is strong.** Learning Plane P0 and Resource Governor RG-0→RG-3E have clean committed qualification; RG-3E E0–E5 is PASS/CLOSE.
2. **Intelligence-growth evidence is still weak.** Method has promising POC evidence, but no pre-registered repeatable unseen-task transfer gate exists yet. Reasoning Lab and Meta-Learning are not qualified.
3. **Integration is the highest immediate engineering risk.** Learning, RG, cache-v2, context elasticity, human-turn queue and registry-refresh work are star-shaped descendants of the same old baseline rather than one ancestry.
4. **Governance execution is incomplete.** Admission-asymmetry rules exist in `AGENTS.md` and `docs/subsystem-disposition-20260909.md`, but they are not yet a submission gate. New control machinery can still land without an explicit model-invokable evidence/veto/recovery exit.
5. **Repository entry state is itself part of convergence.** Local `main` currently points at the context-elasticity tip rather than `lfl/main`, independent fix work is checked out in separate worktrees, and two stashes remain. Branch names alone are therefore not a complete description of live integration state.

Therefore the next system-level action is **not another feature phase**. The required order is:

```text
A    Convergence / file-level disposition
A.5  Governance wiring gate
B    Runtime substrate freeze on one ancestry
C    Phase 3.5 pre-registered measurement loop
D    RG-3F shadow + TrustDomain + adaptive-effort surface + deliberation budgets
E    Reasoning Lab MVP, preferentially as restricted SubAgent profile
F    IndependenceFacts + transfer telemetry
G    Reasoning Skills / Method governance reuse
H    Meta-Learning only after repeated unseen transfer evidence
I    Long-running benchmark as an expansion of Phase 3.5
```

**Freeze rule:** until A/B are complete, do not start another Learning/Reasoning/RG branch from `d59169f`, do not use the currently mispointed local `main` as a new-branch entry point, and do not integrate the current p0a tree wholesale.

---

# 1. Current state correction

## 1.1 The current RG-3E verdict

The current authority is:

`docs/QUALIFICATION-20260910-resource-governor-rg3e-e4.md`

It states:

> RG-3E E4 exact typed mapping = PASS. RG-3E E0-E5 = PASS/CLOSE.

The two older qualification files still contain historical HOLD text:

- `docs/QUALIFICATION-20260910-resource-governor-rg3e.md`
- `docs/QUALIFICATION-20260910-resource-governor-rg3e-e3c.md`

They are historically useful evidence but are **not current status authorities**. During convergence they must receive a visible `[SUPERSEDED 2026-09-10]` banner pointing to the E4/E5 final qualification. Do not rewrite their historical evidence; only disambiguate current authority.

This is a **VERIFIED intra-tree authority conflict**, not merely a naming concern: at the same `cf5e6fb` tree, `rg3e.md` says `E3 = NOT QUALIFIED / RG-3F must not start`, `rg3e-e3c.md` says overall `HOLD`, while `rg3e-e4.md` says `E0-E5 = PASS/CLOSE`. The final E4/E5 document is the current verdict; the older files must remain historical evidence only.

This supersede action is deliberately **listed here rather than silently performed during audit**, so the convergence baseline remains replayable.

## 1.2 Branch topology against the actual formal baseline

Formal baseline is `lfl/main@d59169f`; legacy `origin/main` is not the comparison authority for this workline.

| Line | Current ref | Ahead of `lfl/main` | Current disposition |
|---|---|---:|---|
| Learning P0 clean | `517d7ab` | +3 | REUSE; already ancestor of RG stack |
| current p0a | `8e589de` | +7 | DO NOT MERGE WHOLE TREE |
| RG-3 integration | `9d09a09` | +17 | historical integration waypoint |
| RG-3E qualified | `cf5e6fb` | +22 | **candidate semantic SoT** |
| learning/cache-v2 | `d2efc96` | +6 | HOLD pending defect/disposition |
| context-elasticity | `14c0710` | +13 | HOLD pending characterization/disposition |
| human-turn-queue | `f391520` | +1 | HOLD pending duplicate-dispatch fix |
| CI/RG fallback fixes | `d43612c` | +2 | **ADMIT candidate** after independent review/requalification |

RG-3E relative to `lfl/main` is currently **86 files / +20,263 / -119**. The paired JSON records file-level branch/blob evidence for the union of relevant lines. The convergence target is **not bare `cf5e6fb`**: `cf5e6fb` is the qualified anchor, and independent deltas such as `d43612c` must be carried forward only after their own review/requalification.

## 1.3 Current p0a dirty state is decomposable, not opaque

Current checkout is still `feature/learning-plane-p0a-20260910@8e589de` with 16 tracked dirty files. Byte comparison against P0-clean and RG-3E gives exactly:

- **10** files: current working bytes = P0-clean = RG-3E;
- **4** files: current working bytes = P0-clean, while RG-3E has later qualified evolution;
- **2** files: current working bytes are independent of both qualified trees.

This exact 10/4/2 result is machine-asserted by the paired JSON generator and reproduced below.

### 1.3.1 Ten files: already equal P0-clean and RG-3E — `reuse`

| path | ruling |
|---|---|
| `docs/DESIGN-20260910-learning-plane.md` | REUSE; dirty status is not independent content |
| `docs/METHOD_LEARNING_V1.md` | REUSE |
| `docs/development_methodology.md` | REUSE |
| `src/llm_loop/core/loop/events.py` | REUSE |
| `src/llm_loop/introspection/corrections.py` | REUSE |
| `src/llm_loop/introspection/registry_experience.py` | REUSE |
| `src/llm_loop/introspection/registry_host.py` | REUSE |
| `src/llm_loop/methods/store.py` | REUSE |
| `tests/unit/test_engine_reentrancy.py` | REUSE |
| `tests/unit/test_method_learning.py` | REUSE |

These should **not** be committed as a new p0a contribution during convergence.

### 1.3.2 Four files: equal P0-clean but RG-3E evolved — `replace with qualified RG-3E`

| path | ruling |
|---|---|
| `src/llm_loop/core/loop/engine.py` | REPLACE with RG-3E qualified version |
| `src/llm_loop/methods/learning_plane.py` | REPLACE with RG-3E qualified version |
| `tests/unit/test_learning_journal.py` | REPLACE with RG-3E qualified version |
| `tests/web/test_stream_endpoint.py` | REPLACE with RG-3E qualified version |

The local dirty copies are not “new fixes”; they are an older clean-P0 state. Replaying them over RG-3E would regress later Resource Governor integration.

### 1.3.3 Two files: genuinely independent current dirty — `hold`

| path | ruling |
|---|---|
| `src/llm_loop/tools/mcp_client.py` | HOLD; isolate MCP refresh lifecycle patch |
| `src/llm_loop/tools/registry.py` | HOLD; isolate registry-stack lifecycle patch |

They must be audited and qualified as their own workline before integration. Their presence is not a reason to carry the entire p0a dirty tree forward.

## 1.4 Restart/CI state is already preserved in RG-3E

The following final tree blobs are byte-identical between p0a and RG-3E:

- `scripts/ci_gate.sh`
- `scripts/r9_commit.sh`
- `scripts/restart_mirror.sh`
- `tests/guards/external_red_registry.json`
- `tests/guards/fixture_manifest.json`
- `tests/scripts/test_restart_mirror_hardening.py`
- `tests/unit/test_restart_mirror_script.py`

RG bridge commit `608ec12` already preserved this state. **Do not cherry-pick the p0a restart/CI commits again.**

## 1.5 p0a independent committed delta

`8e589de` changes `src/llm_loop/config.py` and `tests/unit/test_config.py` for a DeepSeek default-model migration. It is not part of Learning semantics and is not automatically entitled to ride the RG convergence. Its own commit message explicitly states that the same operational migration also changed local untracked/ignored `data/providers.json`; therefore reviewing the two committed files alone is incomplete provenance.

Current mechanical observation: `data/providers.json` is not Git-tracked; the observed local file is represented in the paired JSON by SHA-256 only. No provider credential or raw provider-config body is copied into this document.

Disposition: **HOLD / review the committed patch together with sanitized runtime-config provenance, then independently requalify on the eventual unified tree**.


## 1.6 Independent `fix/ci-rg-fallback` line — preserve, do not silently lose

`fix/ci-rg-fallback@d43612c` is a real +2 branch from `d59169f` and is **not** an ancestor of `cf5e6fb`:

- `9b2fff4` — CI guard fallback when `rg` is unavailable, scoped to Python files;
- `d43612c` — first `coordinate` wakeup is decoupled from machine uptime by replacing the `0.0` monotonic sentinel with an explicit never-fired state.

The three affected paths are still byte-identical between `d59169f` and `cf5e6fb`, so the qualified RG-3E line did not independently acquire these fixes. A three-way patch applicability check against `cf5e6fb` passes, but **clean applicability is not qualification**.

Disposition: **ADMIT candidate / preserve for the unified integration, then run focused + committed-state qualification before treating it as integrated truth.** Do not silently discard it and do not label it already qualified.

## 1.7 Local `main` pointer drift — convergence preflight

Mechanical ref state at this audit:

```text
local main = 14c0710 = feature/context-elasticity-20260910 tip
lfl/main   = d59169f = formal baseline for this architecture workline
```

This creates a dangerous branch-entry ambiguity: a future `git switch main && git switch -c ...` would silently inherit the 13 context-elasticity commits.

Required convergence preflight: after re-verifying that `feature/context-elasticity-20260910` preserves `14c0710`, repoint local `main` to the intended formal/integration authority. **This document records the action only; the docs-only phase does not move refs.**

## 1.8 Worktree and stash topology is part of the state

Four current feature worktrees live under the repository's `.worktrees/` root and must be explicitly preserved/inventoried during convergence:

- `rg3-unified-20260910` → `cf5e6fb`;
- `ci-rg-fallback-20260910` → `d43612c`;
- `context-elasticity` → `14c0710`;
- `human-turn-queue` → `f391520`.

They are **not the only Git worktrees**: the repository also retains many historical/detached verification worktrees under `/private/tmp` and backup/tmp locations. Convergence must distinguish active source-bearing worktrees from disposable verification remnants before pruning anything.

Two stashes also exist and are not branch-owned truth:

- `stash@{0}` — context-elasticity `history.py` WIP from the pre-p0a/cache-v2 line;
- `stash@{1}` — 2026-09-05 broad emergency snapshot.

Neither stash may be silently applied or dropped. They require provenance/disposition first.

## 1.9 Untracked architecture drift and count semantics

Current p0a top-level untracked status has **10 entries**: four grouped directories (`.proposals/`, `.tmp/`, `.worktrees/`, `docs/design/`) plus six individual files. The JSON's older `significant_untracked_count=6` referred only to individual file entries; the revised matrix records both scopes explicitly.

Highest priority among these is the untracked Architecture SoT copy:

- qualified RG-3E tracked SoT: **1144 lines**, blob `303bcc9...`;
- p0a untracked copy: **1128 lines**, blob `d6b92bf...`;
- diff versus qualified SoT: local copy has 16 insertions / 32 deletions and lacks the latest RG-3A→RG-3E close/status pointers.

Ruling: the p0a untracked SoT is a **stale local copy**, not a competing authority, and must not overwrite the qualified tracked SoT during convergence.

For size reporting, use explicit reproducible scopes. At this snapshot `src/llm_loop/methods/**/*.py` is **1,348 lines**; do not reuse the earlier undefined `1,425 LOC` figure as a canonical metric.

---

# 2. Four-layer system diagnosis

## 2.1 Mechanical substrate — strong

Already implemented/qualified in the RG-3E ancestry:

- exact Episode boundary and runtime-derived current Episode provenance;
- Learning post-run decoupling from Task completion;
- durable learning journal and foreground-first mechanical admission;
- Resource Governor contracts and local leases;
- provider-call settlement and transport-attempt lineage;
- rebuildable cross-session resource ledger projection;
- authoritative/qualified-unknown provider product facts;
- DeepSeek account balance facts separate from cost budget;
- MiniMax CN Token Plan provider-unit quota with response-derived exact current windows/reset;
- `unknown != zero != unlimited` resource semantics.

## 2.2 Intelligence-growth substrate — beginning, not proven

Method Learning has POC evidence, including one positive unseen transfer canary and a counterexample control, but this is not a pre-registered repeatable transfer qualification.

Do not equate:

```text
candidate count ↑
qualified count ↑
reflection count ↑
```

with:

```text
unseen solved-task rate ↑
foreground cost per solved task ↓
```

The second set is the required intelligence claim.

## 2.3 Engineering integration — current highest risk

The repo currently has a star-shaped topology around the same baseline:

```text
                       p0a
                        |
lfl/main d59169f -------+---- P0 clean ---- RG0 ... RG3E
                        |
                        +---- cache-v2 / learning-plane
                        |
                        +---- context-elasticity
                        |
                        +---- human-turn-queue
                        |
                        +---- fix/ci-rg-fallback (+2, independent)

local main -------------> context-elasticity tip (14c0710), not formal lfl/main
```

Cache/context/queue/registry work all touch or approach Engine/Factory/Session/Prompt/runtime lifecycle surfaces. Continuing feature development before convergence increases conflict and makes qualification evidence tree-dependent.

## 2.4 Governance execution — rules exist, gate is missing

`AGENTS.md` already states Admission asymmetry:

- agency-amplifying capabilities are admitted by default;
- new hard gates / heuristic verdicts / silent truncation / compatibility control must explain why model + existing tools cannot safely decide;
- such controls must provide a documented model-invokable veto/override exit.

`docs/subsystem-disposition-20260909.md` states the same north star.

But current branches demonstrate that this is not yet enforced as a submission review gate. A.5 below turns the policy into an explicit engineering check.

---

# 3. Global ownership matrix

The missing column is **“model-invokable evidence/veto/recovery exit”**. Every control machine must say not only what it owns, but how its mechanical decision is inspectable and contestable where an override is physically/legalistically possible.

| System | Owns | Must not own | Model-invokable evidence / veto / recovery exit |
|---|---|---|---|
| Task Model | semantics, strategy, relevance, Method applicability, completion | physical resource truth | N/A; this is the semantic authority |
| Learning Plane | Episode→candidate workflow; durable learning jobs | Task blocking; automatic Method applicability | candidate may be `none/hold/reject`; Task model may ignore/not retrieve candidate |
| ResourceGovernor | mechanical concurrency/rate/quota/cost/trust admission of an already selected target | semantic provider/model choice; task value/quality | typed refusal + resource facts; model/user may choose a different available action/target through normal authority; no hidden auto-routing |
| StateBraid/backend cache | physical cache/KV admission, slot lifecycle, eviction/restore | semantic relevance or task priority | expose capacity/hit/eviction/restore facts; model may rehydrate evidence, but cannot override physical capacity safety |
| Context elasticity | mechanical window fit, projection/fold | decide which fact is semantically important | stable ref/exact hydration/raw source recovery where available; no silent semantic deletion |
| SubAgent runtime | isolated child lifecycle, durability, cancel, fencing, delivery | deliberation semantics | Task model decides whether to invoke/accept/ignore child/brief |
| EventStore | durable factual source of truth | derived semantic verdict | exact event/evidence retrieval; derived indexes must be rebuildable |
| Ledger projection | rebuildable cross-session mechanical projection | become second durable truth; semantic task admission | expose coverage/conflict/unknown; fall back to EventStore/control-plane evidence |
| ERDC / usage telemetry | cache/prefill/TTFT/token/queue/cost facts | judge Method usefulness | typed raw facts remain inspectable; value stays model/human/eval-owned |
| Adaptive-effort adapter | capability check + apply requested effort + factual receipt | infer task complexity or decide effort | truthful unsupported/unavailable receipt; model picks next effort |
| Deliberation budget guard | hard physical ceiling configuration | decide whether deeper reasoning is worthwhile | expose used/remaining/unknown from settlement truth; model may stop or choose another strategy |

### 3.1 Non-negotiable interpretation of “veto exit”

A veto/override is **not required** for boundaries that cannot safely be overridden, such as:

- physical memory capacity;
- protocol/data-integrity requirements;
- catastrophic safety/authorization boundaries;
- non-repeatable side-effect idempotency where override would violate correctness.

In those cases the change must explicitly state **why no override can exist**, and must still expose factual refusal evidence.

A model veto/override/recovery exit is required when the program is making a reversible mechanical policy choice such as:

- deferring background work;
- compressing a recoverable view;
- choosing a cache retention mode;
- applying a soft resource reservation.

The exit must not become a semantic classifier in reverse.

---

# 4. Pre-integration defect gate

These items must be resolved or characterized **before** their feature branch is admitted to the unified tree.

## 4.1 CACHE-V2-AXIS-REVERSAL — VERIFIED / FIX BEFORE INTEGRATION

Branch: `feature/learning-plane-20260910`, originating cache-v2 commit `f938428`.

### Design contract

`docs/design/ARCHITECTURE-cache-prefix-surface-contract-v1.md` says:

- `system_fp` change → drift → `force_head_keep` + drift count;
- `tools_fp` change → expected/request-surface change → audit only, no drift intervention;
- combined `stable_fp` remains only for physical cache-boundary invalidation/epoch comparison.

### Implemented contract

`src/llm_loop/core/cache_health.py` currently documents/implements the opposite axis judgment in `preflight/postcheck`:

- system/stable change → controlled change/rebase, no intervention;
- tools change → `force_head_keep=True`, drift count and gate marker.

No independent feature flag for this cache-gate behavior was found in the feature's config/source search.

### Ruling

This is a **verified design↔code authority inversion**, not a style difference.

Before integration:

1. decide which contract is current SoT;
2. make implementation/tests/docs agree;
3. explicitly decide default-on vs default-off/rollback surface;
4. record the model evidence/recovery exit for soft cache policy decisions;
5. run stable-prefix/cache hit + no-prompt-drift qualification.

Do not integrate `f938428` unchanged merely because its local tests pass.

## 4.2 HUMAN-TURN-CLAIM-REAPER-DUPLICATE — VERIFIED / FIX BEFORE INTEGRATION

Branch: `feature/webui-human-turn-queue-20260910`, commit `f391520`.

Current queue lifecycle:

```text
queued -> claimed -> completed|failed
              \
               -> after CLAIM_TIMEOUT_S=60 -> queued
```

`_reap_stale_claims_locked()` requeues every `claimed` item older than 60 seconds without checking whether the formal run is still active. Formal queue terminal state is written only from the chat run's terminal callback. Frontend `relayNextQueued()` claims, then fire-and-forgets `sendMessage`, releasing its local relay guard immediately.

Existing test `test_claimed_timeout_reap` explicitly proves that the same `queue_id` becomes claimable again after timeout.

### Failure path

A legitimate model run lasting >60s can still be active while a queue list/dispatch request reaps its claim back to `queued`; another dispatcher can then claim and send the same frozen Human Turn again.

### Ruling

User-visible duplicate-send risk is **verified**.

Required correction should bind claim lifetime to a durable run fact, e.g. a run identity/lease or heartbeat/terminal record. Exact design remains open; do not fix by simply making 60 seconds “larger”. Regression must prove:

> while the first run is mechanically active, a claim older than the nominal stale timeout cannot be re-dispatched; after proven crash/no-active-run state, recovery still works.

## 4.3 T2-PROVIDER-ARCHIVE-ORDER — NEEDS CHARACTERIZATION / DO NOT CALL BUG YET

Branch: `feature/context-elasticity-20260910`.

Observed code shape in `src/llm_loop/core/history.py`:

- turn-rounding path can prepend via `archived[0:0] = ...`;
- several other paths append via `archived.extend(...)`;
- later provider-path `cache_archive_provider` marking consumes `archived`.

This combination may be correct if the documented internal archive ordering is intentionally newest→oldest at one stage and consumed accordingly. No dedicated test was found that injects `cache_archive_provider` and proves the intended provider-visible order across the mixed prepend/append path.

### Required characterization test

Before any fix:

1. construct ordered sentinel turns/groups with unmistakable sequence IDs;
2. exercise the exact T2 path that triggers both round-boundary movement and provider compaction;
3. inject a concrete `cache_archive_provider`;
4. capture returned provider-visible order and archive order separately;
5. assert the intended contract explicitly.

Only after this test may the item move to `verified bug` or `expected behavior`.

This follows `docs/DEVELOPMENT_REPAIR_SAFETY.md`: **characterize the real behavior before repair**.

---

# 5. File-level disposition contract

The complete **134-row** matrix is in:

`docs/analysis/CONVERGENCE-DISPOSITION-20260910.json`

Each row carries:

```text
path
changed_from_baseline_in[]
git_blob.{baseline,p0_clean,p0a,rg3_integration,rg3e,cache_v2,context_elasticity,human_turn_queue,ci_rg_fallback}
working_tree.status/blob_oid/sha256/classification_10_4_2
disposition = admit | reuse | replace | delete | hold
verification_level = verified | needs_characterization | unverified
reason
target_layer
```

### 5.1 Meaning of dispositions

- **reuse** — use the qualified/canonical existing version; do not create another semantic implementation;
- **replace** — older/stale version must give way to a newer qualified authority;
- **delete** — capability or duplicate authority is proven unnecessary; deletion requires its own exact-scope validation;
- **hold** — no integration until evidence/qualification is adequate;
- **admit** — preserve an independently justified capability/fix as an integration candidate with a named target; **admit is not synonymous with already merged or fully qualified**, and any row/branch-specific qualification requirement still applies.

The JSON is a **mechanical replay matrix**, not a second architecture SoT. Semantic rationale lives here; hashes and path facts live in JSON.

**Revision integrity note:** the first docs-only commit `cf77e3c` contained one malformed duplicate matrix path, `ocs/DESIGN-20260910-learning-plane.md`, created by the earlier working-tree path parser. It carried a classification but null hashes while the real `docs/DESIGN-20260910-learning-plane.md` row also existed. This revision removes the malformed row and attaches NUL-delimited porcelain-derived working-tree hashes/classification to the real path. All matrix replay counts below refer to the corrected 134-row matrix.

### 5.2 Verification levels

- `verified` — directly reproduced from branch/blob/code/test evidence;
- `needs_characterization` — code shape is known, behavior interpretation is not yet proven;
- `unverified` — independent work exists but has not received this convergence review.

No agent should silently upgrade `needs_characterization` or `unverified` to a defect/fix merely because the code “looks wrong”.

---

# 6. Branch/component disposition

## 6.1 RG-3E stack — REUSE as qualified semantic anchor

`cf5e6fb` is the best current integration base because it contains:

- clean Learning P0;
- restart/CI preservation bridge;
- RG-0→RG-3E implementation and qualification;
- current Architecture SoT update;
- no cloud enforcement or RG-3F behavior.

This does **not** mean every one of its 20K added lines is permanently accepted, nor that bare `cf5e6fb` is the complete future SoT. It means convergence starts from the most-qualified ancestry; independently reviewed/requalified deltas are then admitted selectively, and disposition may still delete/replace unnecessary machinery.

## 6.2 p0a whole-tree — REJECT as merge unit

Do not merge/cherry-pick the whole p0a branch.

- P0 semantics are superseded by clean P0/RG ancestry;
- restart/CI bytes are already present;
- only the default-model migration is a clear independent committed patch;
- current ToolRegistry/MCP dirty work is independent and unqualified.

## 6.3 default-model migration `8e589de` — HOLD / independent requalification

Provider default model policy is operational configuration, not Learning/RG architecture. Review it against current provider registry/live availability on the eventual unified tree.

## 6.4 cache-v2 — HOLD

First resolve verified axis inversion and admission-asymmetry/rollback questions.

## 6.5 context-elasticity — HOLD

Characterize T2 provider ordering and run a disposition review for T2–T5 before adoption. Context projection may be useful, but it must not become semantic relevance authority.

## 6.6 human-turn-queue — HOLD

Fix duplicate-dispatch path first, then integrate and jointly qualify with foreground scheduling/RG semantics.

## 6.7 MCP refresh / registry-stack dirty — HOLD

The two truly independent dirty source files plus their untracked tests must be isolated, source-bounded and qualified separately. Do not let current p0a dirty status determine their integration ancestry.

## 6.8 `fix/ci-rg-fallback@d43612c` — ADMIT candidate / requalify

Preserve both commits as independent convergence input. Their three paths are absent from the RG-3E delta and the patch mechanically applies to the RG-3E anchor, but integration qualification has not yet been run on the combined tree. Admission here means **do not lose the fixes**; it does not mean skip review/tests.

## 6.9 Local refs / worktrees / stashes — HOLD until provenance disposition

Before constructing the unified tree, correct the local `main` entry pointer, inventory source-bearing worktrees, and classify both stashes. Never delete a worktree or stash merely to simplify the branch graph.

---

# 7. A.5 — Governance wiring gate

This phase is inserted between file convergence and runtime freeze because current policy is written but not mechanically enforced during submission/review.

## 7.1 Four required declarations for new control machinery

Every new hard gate, heuristic verdict, silent truncation, compatibility controller, scheduler policy, cache gate or admission layer must include:

### G1. Necessity

> Why can the model + existing tools/facts not safely make this decision itself?

A vague “for robustness” is insufficient.

### G2. Ownership / non-duplication

> Which existing subsystem owns the underlying fact or lifecycle? Is this `reuse`, `replace`, or a new authority? If new, why is it not a second source of truth?

New Store/Runner/scheduler/governor classes must identify the authority they reuse or replace.

### G3. Model evidence/veto/recovery exit

> When mechanically refused/compacted/deferred, what exact facts can the model inspect, and what reversible override/recovery action is available?

If no override can exist, state the physical/safety/protocol reason explicitly.

### G4. Rollback and verification

> What is the rollback/default-off behavior and which regression proves the control does not silently alter model-visible semantics?

## 7.2 Submission rule

A change that adds control machinery **fails architecture review** if G1–G4 are absent.

Do not make the source build fail based on a semantic string parser. The first implementation should be a repository/PR review gate based on an explicit structured declaration or changed-component manifest, with simple mechanical presence/coverage checks only.

## 7.3 File-level matrix is part of the gate

Every new control change must appear in the disposition matrix (or its successor) with:

- path;
- owning subsystem;
- disposition;
- evidence;
- verification level;
- model evidence/veto/recovery exit;
- rollback route.

This makes the 09-09 admission-asymmetry rule executable as engineering process without creating a program semantic classifier.

---

# 8. Phase 3.5 — pre-registered minimal measurement loop

Phase 3.5 moves **before** Reasoning Lab expansion and Meta-Learning.

## 8.1 Question

The first benchmark must answer exactly:

> Does making a qualified Method discoverable improve performance on truly unseen tasks beyond both base behavior and a retrieval/context placebo?

It is not a benchmark of “how many Methods were created”.

## 8.2 Freeze before observing results

Freeze and record:

- committed runtime SHA;
- exact provider/model configuration;
- tool-surface digest;
- unseen dataset version/digest;
- Method library snapshot/digest;
- evaluation code SHA;
- arm assignment procedure;
- minimum sample count;
- success/HOLD decision rule.

Do not change these after seeing arm results.

## 8.3 Three arms

### A — Base

Target Method is unavailable.

### B — Qualified Method

Target qualified Method is discoverable/hydratable through the same normal retrieval surface. It is **not auto-injected**.

### C — Placebo

An irrelevant or shuffled Method library is available through a matched retrieval/context surface.

Purpose: separate “the useful Method helped” from “having some extra retrieval/context changed behavior”.

## 8.4 Method usage attribution

Record the existing/mechanical usage chain rather than inferring “use” from arm membership:

```text
available
  -> discovered
  -> hydrated
  -> used_or_referenced
  -> final_accept | partial | reject | none
```

`_observe_method_usage`/its current successor may supply hydration observations, but must remain factual telemetry. It must not decide applicability.

## 8.5 Minimum metrics

Primary outcome:

- task success on unseen tasks.

Efficiency/anti-regression outcomes:

- rounds;
- tool calls;
- irrelevant exploration;
- evidence errors / unsupported claims;
- input tokens;
- output tokens;
- cache read/hit;
- prefill time;
- TTFT;
- queue delay;
- wall time;
- settled cost where provider facts permit it.

Where cached pricing or time-of-day pricing affects billing, settlement must preserve the provider-qualified pricing basis/window rather than flattening to one guessed price.

## 8.6 Statistical discipline

Pre-register minimum `n` and decision rule. Reuse existing Wilson confidence-interval machinery where the outcome is binomial and the implementation is appropriate.

Do not specify success after looking at the result.

A reasonable architecture-level gate is qualitative, not hard-coded here:

> if B does not show a repeatable material transfer benefit over both A and C, or if benefit is offset by material correctness/cost regressions, Method expansion and Reasoning Lab/Meta progression remain HOLD.

Exact numerical thresholds belong in the benchmark preregistration artifact for that dataset, not in generic runtime code.

---

# 9. Adaptive Reasoning Control Surface

The architecture title promises adaptive reasoning; this must be a **model-controlled surface**, not a program difficulty classifier.

## 9.1 Control flow

```text
Model requests effort
        |
        v
Provider adapter checks actual capability
        |
        +--> supported: apply requested effort
        |
        +--> unsupported/unavailable: truthful typed result
        v
Return factual receipt
```

No:

```python
if task_complexity > threshold:
    use_deep_reasoning()
```

## 9.2 Factual receipt

Candidate fields:

- `requested_effort`;
- `applied_effort`;
- provider reasoning capability state;
- reasoning token/character count as aggregate telemetry, never hidden CoT;
- input/output tokens;
- cache read/hit facts;
- prefill;
- TTFT;
- wall time;
- queue delay;
- settled cost when known.

## 9.3 Cache-stability rule

The receipt must **not** become a new per-round program-authored narrative injected into the stable prefix.

Preferred delivery:

1. model-requested tool result; or
2. fixed-shape bounded factual receipt on an already-dynamic surface.

It must:

- never mutate the stable system/tools prefix merely because another round occurred;
- never accumulate a growing prose history of “effort advice”;
- remain recoverable through normal evidence/receipt mechanisms if needed.

The model decides whether the previous effort was worth its cost and what to request next.

---

# 10. Deliberation mechanical budget contract

Reasoning Lab must not get an unconstrained “think as much as desired” runtime.

Candidate hard boundaries include:

- recursion depth = 1 initially;
- at most one active Deliberation for a source Episode initially;
- per-run token ceiling;
- per-run wall-time ceiling;
- per-Episode accumulated ceiling;
- truthful refusal/timeout receipt;
- no silent truncation claimed as a valid complete Brief.

These are mechanical limits, not semantic judgments about whether the problem deserves deeper thought.

## 10.1 Single accounting authority

**Consumed usage must come from RG-3C/RG-3D settlement/ledger facts.**

DeliberationRunner may hold the configured ceilings. It must **not** maintain a second authoritative token/time/cost counter that can disagree with settlement.

Thus:

```text
ceiling configuration -> Deliberation/RG policy input
actual consumption     -> provider-call settlement / ledger SoT
remaining              -> mechanical projection of the two
```

And always:

`unknown != zero != unlimited`.

---

# 11. Reasoning Lab implementation disposition

Logical architecture may still call the unit `DeliberationRun`, but the physical implementation should first try to **reuse SubAgent runtime**.

Preferred MVP:

```text
SubAgentRunner
  + restricted deliberation profile
  + no parent conversation inline
  + read-only Method / Experience / Rule / Skill / Evidence retrieval
  + no recursive Deliberation/SubAgent
  + closed ReasoningBrief schema
  + existing cancel/durability/fencing/settlement
  = DeliberationRun behavior
```

Only gaps proven impossible to reuse justify a new runtime component.

`ReasoningBrief` should not create another fact store:

```text
EventStore                 = lifecycle truth
Artifact/Evidence storage  = structured Brief body
rebuildable index          = search/projection only
```

Brief delivery should be **model-requested**, not automatically injected into every Task prompt.

Task model remains final authority to accept, partially use, reject or ignore the Brief.

---

# 12. Qualification independence as recorded facts, not a semantic classifier

Current invariant `qualification_episode_ref != source_episode_ref` remains necessary but is not sufficient to describe independence.

Add mechanical `IndependenceFacts`, for example:

- `different_episode`;
- `different_session`;
- `different_benchmark_case`;
- `different_workspace`;
- `different_provider`;
- `different_model`;
- `time_separation`;
- `counterexample_attempt_ref`.

Program responsibilities:

- prove each claimed dimension mechanically;
- persist provenance;
- reject spoofed refs;
- expose the fact set.

Program must **not** decide that a semantic `task_family` is or is not sufficiently different. Do not add a generic `task_family` classifier merely to obtain a qualification checkbox.

Likewise do not hard-code “k=3 means independent” in runtime architecture. Empirical benchmark preregistration may require sample counts, but that is evaluation design, not task-semantic authority.

A counterexample attempt should be referencable and durable. Whether it is a meaningful counterexample remains model/human evaluation judgment.

---

# 13. Cache/context ownership coordination

## 13.1 StateBraid / backend cache

Owns physical KV/cache lifecycle and capacity mechanics. Learning/Reasoning should express mechanical cache intent through the existing Harness contract, e.g. transient/non-pin semantics where qualified.

ResourceGovernor must not grow a second semantic cache policy brain.

## 13.2 Context elasticity

May own mechanical projection/window fit, but must preserve recoverability and avoid semantic relevance judgments.

Any adaptive compression controller must expose:

- exact reason/fact for compression;
- what representation changed;
- stable recovery refs;
- provider/cache epoch effects;
- a model-invokable recovery path where physically possible.

## 13.3 ERDC / cache measurements

Cache hit, prefill, TTFT, GPU/runtime timing and provider settlement are measurements. They are not proof that a Method or Brief is semantically useful.

Phase 3.5 combines these facts with task outcomes rather than turning them into a new heuristic gate.

---

# 14. Stale-document reconciliation rule

The RG-3E document collision demonstrates a reusable documentation failure mode:

```text
same phase name
+ multiple incremental qualification files
+ earlier file has the most canonical-looking name
+ no superseded marker
= future agent reads a false current verdict
```

Convergence action:

- preserve old evidence verbatim;
- add a top-of-file `[SUPERSEDED <date>]` banner;
- point to exactly one current status authority;
- current Architecture SoT links the current authority first.

Do not delete historical qualification evidence merely because its verdict was later superseded.

This action applies immediately to the two RG-3E historical HOLD files listed in §1.1 after the convergence plan itself is accepted/committed.

---

# 15. Unified integration construction rule

When actual convergence begins:

0. verify `feature/context-elasticity-20260910@14c0710` preserves the current local-main tip, then repoint local `main` away from that feature tip before any new branch is cut;
1. start from qualified `cf5e6fb` as the semantic anchor, not current p0a;
2. preserve and independently review/requalify `fix/ci-rg-fallback@d43612c`; admit its qualified result rather than silently losing it;
3. do not whole-merge p0a;
4. do not replay restart/CI assets already byte-identical in RG-3E;
5. review/requalify `8e589de` together with sanitized `data/providers.json` provenance, not the commit in isolation;
6. separately isolate/qualify MCP/registry-stack dirty work;
7. resolve cache-v2 verified defect before admitting cache-v2;
8. characterize T2 provider archive ordering before repair/admission;
9. fix human-turn-queue duplicate path before admission;
10. inventory/disposition source-bearing worktrees and both stashes before pruning or applying anything;
11. then selectively port only qualified cache/context/queue/independent deltas;
12. run committed-state integration gates and live qualification relevant to the merged behavior.

The resulting unified integration branch becomes the **only allowed ancestor for subsequent Learning/Reasoning/RG work** until this architecture phase closes.

## 15.1 Phase 3.5 baseline freeze

Once the Phase 3.5 experiment baseline is cut:

- no unrelated feature may be silently absorbed between arms;
- model/provider/tool-surface changes require a new experiment version;
- Method library mutation after freeze requires a new snapshot/digest;
- cache/context changes require a new baseline if they affect the provider-visible trajectory.

This is necessary for causal attribution.

---

# 16. What is explicitly not being done now

This convergence gate does **not** authorize:

- RG-3F enforcement;
- cloud blocking based on projected quota/rate/cost;
- automatic provider/model switching;
- TrustDomain enforcement before its own contract/qualification;
- Reasoning Lab runtime creation;
- Meta-Learning;
- automatic Method promotion;
- semantic task complexity classifiers;
- hard-coded task-family independence classifiers;
- new program-authored prompt injection for effort or cache advice;
- branch-wide reset/merge of the current dirty p0a checkout.

---

# 17. Exit criteria for Convergence Gate A/A.5

A/A.5 may close only when all are true:

1. paired JSON matrix covers every file in the selected branch union and current relevant dirty set, including `fix/ci-rg-fallback`;
2. 10/4/2 working-tree classification remains mechanically reproducible or changes are explicitly re-baselined;
3. local `main` no longer points at the context-elasticity feature tip and its prior tip remains preserved by a named feature ref;
4. source-bearing worktrees and both current stashes have explicit preserve/admit/drop dispositions before any cleanup;
5. RG-3E stale qualification files are marked superseded without destroying historical evidence;
6. the stale p0a untracked Architecture SoT is prevented from overwriting the qualified tracked SoT;
7. `fix/ci-rg-fallback@d43612c` is independently reviewed and requalified on the integration anchor before admission;
8. cache-v2 axis mismatch is resolved and qualified;
9. human-turn claim/reaper duplicate path is fixed and regression-tested;
10. T2 provider archive ordering has a characterization verdict (`bug` or `expected`), not an inference;
11. p0a default-model migration receives an independent provider/config disposition that includes sanitized `data/providers.json` provenance;
12. MCP/registry-stack dirty work receives an independent provenance/qualification verdict;
13. cache/context/queue branch changes receive file-level dispositions;
14. A.5 G1–G4 control-machine declarations are represented in review/submission workflow;
15. a single unified integration ancestry is created and clean committed-state gates pass;
16. Phase 3.5 preregistration artifact is frozen before its first result is observed.

Only after 1–16 should the architecture proceed to intelligence-layer expansion.

---

# 18. Recommended immediate execution sequence

```text
Step 0  Preserve the context-elasticity feature ref, then repoint local main away from 14c0710 before new branches are cut.
Step 1  Mark two stale RG-3E HOLD qualification docs SUPERSEDED -> E4/E5 current authority.
Step 2  Review/requalify fix/ci-rg-fallback@d43612c against the RG-3E anchor; preserve it unless disproven.
Step 3  Characterize T2 archive order; no source fix until result exists.
Step 4  Fix/qualify cache-v2 axis contract and human-turn reaper duplicate path independently.
Step 5  Review default-model migration + sanitized providers.json provenance and MCP/registry stack independently.
Step 6  Inventory/disposition source-bearing worktrees, detached verification remnants, and both stashes before cleanup.
Step 7  Construct one integration branch from qualified RG-3E and selectively port only qualified/admitted deltas.
Step 8  Full committed-state + relevant live qualification; freeze Runtime Substrate B.
Step 9  Write/freeze Phase 3.5 preregistration and run A/B/placebo.
Step 10 Decide from measured transfer whether RG-3F/Reasoning Lab progression is justified.
```

The ordering is intentionally conservative: **converge → instrument → measure → add intelligence**, rather than **add more machinery → measure at the end**.

---

# 19. Evidence and replay notes

The paired JSON is generated from Git blob identities rather than narrative comparison. After the path-parser correction documented in §5, it includes:

- all relevant branch commit IDs, including the independent CI/RG fallback line;
- the local `main` pointer observation and worktree/stash topology notes;
- changed-path union;
- per-ref Git blob OIDs;
- current working-tree blob OID + SHA-256 for tracked dirty files;
- exact 10/4/2 classification;
- branch source membership;
- disposition and verification level;
- significant current untracked artifacts with explicit top-level-vs-file count scope;
- sanitized hash-only provenance for ignored `data/providers.json`;
- three pre-integration defect records;
- ownership/veto policy;
- A.5 gate;
- Phase 3.5 preregistration skeleton;
- adaptive effort / deliberation budget / IndependenceFacts constraints.

The JSON intentionally does **not** contain credentials, API keys, provider balances, raw HTTP headers, raw control-plane bodies, or private user content.

---

# 20. Final architecture ruling

The current project should no longer be described as “Learning/Resource architecture not yet implemented”. A more accurate state is:

> **Mechanical substrate: strong | Intelligence growth: beginning | Engineering integration: highest current risk | Governance execution: rules written, gate not yet wired.**

The next optimization target is therefore not another feature count. It is to create one coherent, falsifiable system in which:

- each mechanical controller has one authority and an evidence/override/recovery story;
- each learned Method must earn its place through unseen transfer;
- each new intelligent capability reuses existing durable/runtime primitives before adding another layer;
- each future claim of “smarter” can be distinguished from “more code, more context, or more cost”.

That is the convergence criterion for moving LFL from a collection of qualified feature lines into one sustainable adaptive-reasoning system.
