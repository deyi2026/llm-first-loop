# Agent Qualification Envelope v0.1 — Read-only Design

> Status: **READ-ONLY DESIGN / NOT A GATE / NOT RUNTIME-WIRED**
> Baseline: `e6621d6d48a407d418d9c0ca63d87a96c717d739`
> Runtime-qualified parent: `b9b312c16ddf2af55fbf981f92f5b3cb71d7f001`
> Scope: unify references to existing qualification facts without creating a new source of truth.
> Non-goals: no runtime change, no scorer change, no global step/redundancy threshold, no new blocking authority.

## 0. Ruling

LFL already owns several independent qualification mechanisms:

1. durable Goal/Task mechanical completion checks;
2. EvidenceRef authenticity/integrity verification for Task completion;
3. scenario-level trace verdicts;
4. calibrated semantic scorers and pre-registered screening rules;
5. runtime/build/config/provider identity manifests and canary evidence;
6. the A.5 architecture-submission governance contract.

The missing capability is not another scorer. The missing capability is a **read-only evidence envelope** that can show, for one declared subject/profile, which of those existing authorities say what, with exact provenance and explicit `unknown/not_applicable` handling.

**Envelope v0.1 has no blocking right.** It does not decide whether an Agent, Goal, deployment, PR, or release is qualified. It does not reinterpret the facts it reads. It does not become a second durable ledger. It has no universal `qualified=true/false` field.

Any future change that gives the Envelope blocking/admission authority is a **new control machine** and requires a separate A.5 G1–G4 declaration and qualification before wiring.

---

## 1. Why this is needed

Today the relevant signals are real but disconnected:

- Goal completion reads Task frontier state, while eval verdicts do not know about the durable Goal;
- Task Evidence verification proves owner/ref/blob integrity, but deliberately does not judge evidence relevance or sufficiency;
- calibrated scorers judge Decision/constraint/fatal/novel behavior, but are benchmark-scoped rather than durable Goal authorities;
- trace verdicts can produce binary outcomes for a declared eval scenario, but are not universal runtime trajectory policy;
- deployment qualification already has exact git/config/provider/build identity facts, but those facts live outside the semantic scorer;
- A.5 specifies a repository/review gate for **new control machinery**, not a user-Goal completion gate.

A read-only Envelope can join these references without joining their authorities.

---

## 2. Authority boundary

### 2.1 Envelope is a view, not a truth owner

For every field, v0.1 must carry:

```text
value
source_status = present | unknown | not_applicable
owner
source_ref
source_revision
classification = HARD | PREREGISTERED | SCORE | DIAGNOSTIC
policy_ref (when a pre-registered/frozen rule interprets the value)
```

The Envelope may normalize serialization shape, but it must not recompute a semantic verdict when the owning subsystem already emits one.

Examples:

- `goal_completion_ready` is read from TaskStore-derived truth; Envelope must not recalculate task semantics from prose.
- `task_success` is imported from the frozen scorer output; Envelope must not infer it from final-answer text itself.
- `config_hash` is imported from Runtime Manifest; Envelope must not invent an alternate configuration hash.
- `unnecessary_verification_count` may be displayed as a diagnostic fact, but Envelope must not apply a new global ratio threshold.

### 2.2 Missing is not pass

If an owner cannot be read, v0.1 emits `source_status=unknown`. It must not convert missing data to `pass`, `0`, or `false`.

This matters especially for Goal completion. `TaskStore.goal_completion_ready()` is a mechanical boolean when the frontier is available (`src/llm_loop/introspection/task_store.py:448-457`), but the current `update_goal(complete)` wrapper intentionally catches TaskStore exceptions and fails open (`src/llm_loop/introspection/tools_goal.py:223-240`). The Envelope must preserve that distinction rather than claim that every persisted Goal `complete` necessarily proves the completion precheck was successfully observed.

### 2.3 No universal aggregation in v0.1

The following field is intentionally **absent**:

```text
qualified: true | false
```

Different profiles already have different frozen policies. A deployment qualification, an S2 anchor screen, a durable Goal, and an architecture submission are not interchangeable subjects.

---

## 3. Classification semantics

### HARD

A mechanically checkable invariant already owned by an existing subsystem, or an exact identity/integrity comparison whose expected value is explicitly declared by the qualification profile. Envelope only forwards the owner result/fact.

Examples: open Task frontier blocking Goal completion; required EvidenceRef existence/authorization/blob integrity; exact runtime git/config identity match in a declared deployment qualification.

### PREREGISTERED

A binary/classification rule whose thresholds/semantics are frozen **before** observing the measured outputs and whose scope is explicitly bounded.

Examples: eval scenario verdict selection; S2 anchor-only screening classification; a declared canary matrix.

### SCORE

A semantic scorer/judge output. It may be decisive inside its own frozen benchmark protocol, but it is not automatically a universal runtime hard gate.

Examples: `task_success`, `fatal_behavior`, `constraint_violation`, `novel_stage`.

### DIAGNOSTIC

An observed metric/fact that is useful for analysis but must not become a universal failure threshold without a separate pre-registered policy and, if wired as a controller, A.5 review.

Examples: reasoning length, reflection count, raw unnecessary-verification count, latency, total rounds/tool calls.

---

## 4. Current source map

### 4.1 Durable Goal / Task completion

Authoritative facts:

- Task frontier `open_count` is the count of `pending/in_progress/blocked` tasks: `src/llm_loop/introspection/task_store.py:438-445`.
- `goal_completion_ready()` returns true only when `open_count == 0`: `src/llm_loop/introspection/task_store.py:448-457`.
- `update_goal(..., status=complete)` invokes that check and rejects when it returns false: `src/llm_loop/introspection/tools_goal.py:223-238`.
- the wrapper catches unexpected TaskStore errors and continues: `src/llm_loop/introspection/tools_goal.py:239-240`; therefore “precheck unavailable” must remain distinguishable from “precheck passed”.

The program owns only mechanical state/lifecycle. CONVERGENCE keeps Task Model authority over semantics/strategy/relevance/completion (`docs/analysis/CONVERGENCE-DISPOSITION-20260910.md:428-444`).

### 4.2 Task Evidence authenticity / integrity

For a Task entering `done`:

- if `evidence_required=true`, empty `evidence_refs` is rejected: `src/llm_loop/introspection/task_store.py:269-274`;
- refs are verified on entering `done` or when refs changed: `src/llm_loop/introspection/task_store.py:275-291`.

Verifier boundary is explicit:

- it checks whether declared refs resolve inside the current trusted owner scope and whether immutable blobs remain intact;
- it **never** refreshes source freshness and **never** judges relevance, sufficiency, acceptance, or task completion: `src/llm_loop/introspection/task_evidence.py:1-6`;
- authorization/ref resolution is checked at `src/llm_loop/introspection/task_evidence.py:90-102`;
- blob missing/corruption is checked at `src/llm_loop/introspection/task_evidence.py:103-120`;
- successful verification is returned mechanically at `src/llm_loop/introspection/task_evidence.py:130-135`.

### 4.3 Existing trace verdicts

`src/llm_loop/eval/verdicts.py` already contains binary trace/answer verdicts:

- `tool_used`: `86-91`;
- `chain_complete`: `94-105`;
- `adjust_step`: `108-112`;
- `honest_failure`: `121-137`;
- `no_repeat_tool`: `140-146`.

Existing exact-repeat scope is narrower than a general trajectory loop detector:

- `_same_fingerprint()` compares only adjacent calls using `(name, normalized arguments)`: `src/llm_loop/eval/verdicts.py:60-70`.

Therefore v0.1 must not describe non-adjacent `A -> B -> A` recurrence as already covered.

These verdict functions become pass/fail only when a scenario selects them. `run_verdict()` dispatches the named verdict and returns false on unknown/exception: `src/llm_loop/eval/verdicts.py:178-186`. The Envelope classifies a selected verdict as **PREREGISTERED**, not as a universal runtime HARD rule.

### 4.4 Calibration / semantic scoring

C1 scorer v1.4 explicitly separates semantic task success from verification depth and verbosity:

- reasoning length/reflection is calculated as a verbosity dimension: `scripts/calib/scorer.py:355-360`;
- unnecessary verification counts unexpected/repeated requested sources: `scripts/calib/scorer.py:370-377`;
- `novel_stage` has its own N0–N4 transition: `scripts/calib/scorer.py:379-398`;
- `task_success` is final Decision match + no constraint/fatal, and the code explicitly states Novel depth is independent: `scripts/calib/scorer.py:400-415`;
- outputs expose task/fatal/constraint/novel/unnecessary/reasoning as distinct fields: `scripts/calib/scorer.py:430-450`.

The calibrated H2 core keeps the same separation and emits `v1.6-h2`: `scripts/calib/h2_scorer.py:573-619`.

S1 adapter documents the same orthogonality:

- `task_success`, `novel_stage`, waiver, unnecessary verification, reasoning diagnostics are separate: `docs/SCREENING-SCORER-S1-v1.md:63-69`;
- its 96-run dry pass is execution/scoring plumbing evidence, not model evidence: `docs/SCREENING-SCORER-S1-v1.md:71-83`.

### 4.5 S2: raw efficiency metric vs frozen screening rule

S2 is important because it proves that the **same raw metric can have two different classes**:

- raw repeated/unexpected source count is computed as `unnecessary`: `scripts/calib/analyze_s2.py:18-26` and aggregated at `48-57`; this raw value remains DIAGNOSTIC;
- the frozen S2 matrix pre-registers provider-relative screen-out/screen-in thresholds: `docs/SCREENING-S2-MATRIX-v1.md:7-14`;
- those frozen thresholds are applied at `scripts/calib/analyze_s2.py:59-105`.

Thus `unnecessary_verification_count > N` is **not** a universal hard invariant. It can participate in a **PREREGISTERED** screening rule when the scope, comparator, threshold and freeze discipline were declared before outcomes.

The actual S2 result remains explicitly anchor-only, not global promotion evidence: `docs/SCREENING-S2-ANCHOR-RESULT-v1.md:1-18,65,121`.

### 4.6 Runtime / deployment identity

LFL already has a runtime identity/config source of truth:

- Runtime Manifest declares itself the verifiable fingerprint of runtime identity/config: `src/llm_loop/runtime/manifest.py:1-12`;
- `config_hash()` hashes the redacted EffectiveConfig summary: `src/llm_loop/runtime/manifest.py:38-44`;
- provider source priority/hash attribution is mechanical: `src/llm_loop/runtime/manifest.py:75-123`;
- manifest fields include exact git head, identity status, build identity, model/provider, token/window facts, config sources/hash and provider hashes: `src/llm_loop/runtime/manifest.py:195-244`;
- manifest persistence/read path is `src/llm_loop/runtime/manifest.py:247-267`;
- `/health` identity is a read-only projection of manifest facts: `src/llm_loop/runtime/manifest.py:287-299`.

Configuration authority is separately defined by the resolver:

- CLI > explicit runtime override > runtime-root dotenv > defaults, with stale shell env not authoritative: `src/llm_loop/runtime/resolver.py:1-17`;
- effective values and sources are resolved mechanically at `src/llm_loop/runtime/resolver.py:108-168`;
- dual-root runtime config prefers `LFL_RUNTIME_ROOT`, while source identity may use `LFL_WORKSPACE_ROOT`: `src/llm_loop/runtime/resolver.py:171-185`.

Launch writes the manifest from the resolved config and identity report before service execution: `src/llm_loop/runtime/launch.py:41-65`.

Build identity is prompt-neutral and explicitly does not select provider/model/task policy: `src/llm_loop/runtime/build_identity.py:1-10`; exact git/dirty/release facts are computed at `47-53,59-80,128-139`.

`RuntimeCausalSnapshot` consumes the existing manifest rather than inventing another identity, and binds git/config/provider hashes with source-tree/tool/rules fingerprints: `src/llm_loop/runtime/causality.py:88-107`.

Operational restart evidence is independently persisted with exact full git SHA and return code: `scripts/restart_mirror.sh:364-395`.

The current qualification report demonstrates how those facts were used for exact b9b promotion without making the docs commit itself a runtime target:

- evidence boundary: `docs/QUALIFICATION-20260915-gate-e-promotion.md:5-18`;
- restored config identity and GLM/Ornith requalification: `95-150`;
- token-native cache promotion boundary: `156-198`;
- official b9b restart/proc/runtime-manifest evidence: `200-217`;
- WebUI artifact is a distinct qualification requirement not implied by Python CI: `219-242`;
- Gate A–E summary and main/release non-authorization: `301-318`.

### 4.7 A.5 architecture-submission governance

CONVERGENCE is explicit that the missing governance gate is a submission/review gate:

- `docs/analysis/CONVERGENCE-DISPOSITION-20260910.md:414-424` says rules exist but are not yet enforced as a submission review gate;
- ownership matrix says Task Model owns semantics/strategy/relevance/completion while mechanical systems must expose evidence/recovery boundaries: `428-455`;
- A.5 requires G1 Necessity, G2 Ownership/non-duplication, G3 model evidence/veto/recovery, G4 rollback/verification: `657-685`;
- a new control machine fails architecture review when G1–G4 are absent, but the first implementation must be a structured declaration/changed-component manifest with **mechanical presence/coverage checks only**, not a semantic string-parser build failure: `687-705`;
- the convergence exit criteria require G1–G4 to be represented in review/submission workflow: `1068-1087`.

---

## 5. Envelope v0.1 field matrix

`Current status` describes the exact `e6621d6d` baseline. Classification describes how the Envelope may consume the fact; it does not change the owner's semantics.

| Envelope field | Classification | Existing owner / SoT | Exact source | Current status / v0.1 rule |
|---|---|---|---|---|
| `mechanical.goal.open_count` | HARD | TaskStore frontier | `src/llm_loop/introspection/task_store.py:438-445` | Existing mechanical fact. Do not infer from prose. |
| `mechanical.goal.completion_ready` | HARD | TaskStore | `src/llm_loop/introspection/task_store.py:448-457` | Existing boolean when source is readable. |
| `mechanical.goal.completion_precheck_observed` | DIAGNOSTIC | update_goal wrapper observation | `src/llm_loop/introspection/tools_goal.py:223-240` | GAP: no persisted precheck-observed field today. Needed to distinguish observed pass from fail-open exception path; until a direct invocation receipt exists, source_status=unknown, never pass. |
| `mechanical.task.evidence_required` | HARD | TaskStore task record | `src/llm_loop/introspection/task_store.py:269-274` | Existing completion precondition. |
| `mechanical.task.evidence_verification_status` | HARD | TaskEvidenceVerifier / TaskStore | `src/llm_loop/introspection/task_store.py:275-291`; `src/llm_loop/introspection/task_evidence.py:61-135` | Authenticity/integrity only. Never label semantic sufficiency. |
| `mechanical.task.evidence_refs_digest` | HARD | TaskEvidenceVerifier | `src/llm_loop/introspection/task_store.py:289-291`; `src/llm_loop/introspection/task_evidence.py:61-64,130-135` | Existing mechanical digest when verification ran. |
| `runtime.git_head` | HARD | Runtime Manifest | `src/llm_loop/runtime/manifest.py:195-244` | Exact identity fact; match expectation only if profile declares expected SHA. |
| `runtime.identity_ok` | HARD | IdentityReport -> Runtime Manifest | `src/llm_loop/runtime/manifest.py:218-225` | Existing fact. Envelope does not change shadow/enforce launch policy. |
| `runtime.build_identity` | HARD | build_identity -> Runtime Manifest | `src/llm_loop/runtime/build_identity.py:47-53,59-80,128-139`; `src/llm_loop/runtime/manifest.py:226-227` | Exact tracked-source/release facts. |
| `runtime.config_hash` | HARD | EffectiveConfig / Runtime Manifest | `src/llm_loop/runtime/manifest.py:38-44,228-240` | Exact config fingerprint; expected hash must come from declared qualification profile/evidence. |
| `runtime.config_sources` | HARD | EffectiveConfig / Runtime Manifest | `src/llm_loop/runtime/resolver.py:108-168`; `src/llm_loop/runtime/manifest.py:228-240` | Preserve per-key source; do not flatten into a second precedence system. |
| `runtime.providers_effective_hash` | HARD | Runtime Manifest | `src/llm_loop/runtime/manifest.py:75-123,242-244` | Existing provider-source identity. |
| `runtime.causal_snapshot_id` | HARD | RuntimeCausalSnapshot | `src/llm_loop/runtime/causality.py:88-107` | Existing immutable causal identity card; view only. |
| `deployment.restart_receipt` | HARD | official restart script receipt | `scripts/restart_mirror.sh:364-395` | Existing exact action/rc/git SHA evidence. |
| `trajectory.eval_verdict_name` | PREREGISTERED | eval scenario + verdict registry | `src/llm_loop/eval/verdicts.py:75-83,178-186` | Only meaningful with declared scenario/policy. |
| `trajectory.eval_verdict_pass` | PREREGISTERED | named verdict implementation | `src/llm_loop/eval/verdicts.py:86-146` | Do not promote a scenario verdict into universal runtime policy. |
| `trajectory.adjacent_duplicate_fingerprint` | PREREGISTERED | `no_repeat_tool` helper | `src/llm_loop/eval/verdicts.py:60-70,140-146` | Existing adjacent-only behavior. Non-adjacent recurrence is **not implemented**. |
| `semantic.task_success` | SCORE | frozen scorer/judge | `scripts/calib/scorer.py:400-415,430-450`; `scripts/calib/h2_scorer.py:573-619` | Semantic benchmark output; not durable Goal truth. |
| `semantic.constraint_violation` | SCORE | frozen scorer/judge | `scripts/calib/scorer.py:400-415,430-450`; `scripts/calib/h2_scorer.py:573-619` | Keep scorer version attached. |
| `semantic.fatal_behavior` | SCORE | frozen scorer/judge | `scripts/calib/scorer.py:400-415,430-450`; `scripts/calib/h2_scorer.py:573-619` | Keep scorer version attached. |
| `semantic.novel_stage` | SCORE | frozen scorer/judge | `scripts/calib/scorer.py:379-398,430-450` | Verification-depth score; independent of task_success in C1. |
| `semantic.source_conflict_resolved` | SCORE | frozen scorer/judge | `scripts/calib/scorer.py:400-415,430-450` | Scorer-owned semantic predicate. |
| `trajectory.unnecessary_verification_count` | DIAGNOSTIC | scorer / S2 analyzer | `scripts/calib/scorer.py:370-377`; `scripts/calib/analyze_s2.py:18-26` | Raw count only. No global fail threshold. |
| `trajectory.reasoning_chars` | DIAGNOSTIC | scorer | `scripts/calib/scorer.py:355-360,430-450` | Diagnostic only unless a future protocol preregisters a scoped rule. |
| `trajectory.reasoning_reflection_count` | DIAGNOSTIC | scorer | `scripts/calib/scorer.py:355-360,430-450` | Diagnostic only. |
| `trajectory.decisive_action_turn` | DIAGNOSTIC | scorer | `scripts/calib/scorer.py:417-420,448` | Observed endpoint, no universal max-turn rule. |
| `screening.s2_classification` | PREREGISTERED | frozen S2 matrix/analyzer | `docs/SCREENING-S2-MATRIX-v1.md:7-14`; `scripts/calib/analyze_s2.py:59-105` | Anchor-only frozen policy; not global Agent qualification. |
| `screening.s2_scope` | HARD | frozen S2 protocol/result metadata | `docs/SCREENING-S2-MATRIX-v1.md:14`; `docs/SCREENING-S2-ANCHOR-RESULT-v1.md:1-5` | Must preserve scope so anchor-only evidence cannot be upgraded to cross-vendor claim. |
| `deployment.live_canary_profile` | PREREGISTERED | qualification report/protocol | `docs/QUALIFICATION-20260915-gate-e-promotion.md:122-150,182-198` | Pass/fail only inside exact declared canary boundary. |
| `deployment.webui_artifact_gate` | PREREGISTERED | release qualification | `docs/QUALIFICATION-20260915-gate-e-promotion.md:219-242` | Separate gate; Python CI is insufficient evidence. |
| `governance.g1_present` | HARD | A.5 declaration manifest | `docs/analysis/CONVERGENCE-DISPOSITION-20260910.md:661-669` | Required by design, **not yet wired**. Presence only in first implementation. |
| `governance.g2_present` | HARD | A.5 declaration manifest | `docs/analysis/CONVERGENCE-DISPOSITION-20260910.md:671-675` | Required by design, not yet wired. |
| `governance.g3_present` | HARD | A.5 declaration manifest | `docs/analysis/CONVERGENCE-DISPOSITION-20260910.md:677-681` | Required by design, not yet wired. |
| `governance.g4_present` | HARD | A.5 declaration manifest | `docs/analysis/CONVERGENCE-DISPOSITION-20260910.md:683-685` | Required by design, not yet wired. |
| `governance.file_coverage_present` | HARD | disposition matrix / successor | `docs/analysis/CONVERGENCE-DISPOSITION-20260910.md:693-705` | Mechanical presence/coverage only; no semantic parser. |

---

## 6. Proposed read-only envelope shape

This is a serialization contract proposal only. It is not implemented by v0.1.

```json
{
  "schema": "agent-qualification-envelope/v0.1",
  "subject": {
    "profile": "durable-goal | benchmark-run | deployment | architecture-submission",
    "id": "opaque subject id",
    "expected_revision": "optional predeclared revision"
  },
  "facts": [
    {
      "field": "runtime.git_head",
      "classification": "HARD",
      "value": "...",
      "source_status": "present",
      "owner": "runtime_manifest",
      "source_ref": "data/runtime/runtime_manifest.json",
      "source_revision": "...",
      "policy_ref": null
    }
  ],
  "coverage": {
    "present": 1,
    "unknown": 0,
    "not_applicable": 0
  },
  "aggregate_verdict": "not_evaluated"
}
```

Normative v0.1 properties:

1. `aggregate_verdict` is always `not_evaluated`.
2. `owner` cannot be `envelope` for a substantive qualification fact.
3. unknown source state remains unknown.
4. SCORE values retain scorer/judge version.
5. PREREGISTERED values retain policy/matrix/protocol identity.
6. HARD values retain the owner result and the exact expected identity only when the profile supplied it before evaluation.
7. DIAGNOSTIC values have no implicit threshold.

---

## 7. Profiles, not one global gate

### 7.1 `durable-goal`

May present:

- Goal status;
- Task frontier/open count;
- completion-ready observation;
- Task evidence integrity facts;
- linked benchmark/eval results only when an explicit relation exists.

It must not infer semantic completion from `task_success`, nor infer `task_success` from Goal status.

### 7.2 `benchmark-run`

May present:

- frozen scorer version;
- semantic SCORE fields;
- selected trace verdicts;
- raw trajectory diagnostics;
- pre-registered matrix/classification identity.

It must not mutate Goal/Task state.

### 7.3 `deployment`

May present:

- expected vs observed git/config/provider/build identity;
- restart receipt;
- committed/static gates;
- declared live canary evidence;
- distinct artifact gates such as WebUI build.

It must not infer task quality from runtime health.

### 7.4 `architecture-submission`

May present A.5 G1–G4 declaration and file-coverage presence.

The first wired A.5 implementation, if authorized later, should check only structured presence/coverage as required by `docs/analysis/CONVERGENCE-DISPOSITION-20260910.md:687-705`. Semantic quality of the declaration remains review/model/human judgment.

---

## 8. Envelope v0.1 self-declaration under A.5

Even though v0.1 is non-blocking, its boundary is documented now so a future implementation cannot silently become a new authority.

### G1 — Necessity

Existing qualification facts are split across durable task state, Evidence integrity, benchmark scorers, trace verdicts, runtime manifests and release/governance evidence. A read-only joined view reduces evidence fragmentation without asking the program to decide semantic task value.

### G2 — Ownership / non-duplication

**Reuse only.** Envelope owns serialization/provenance projection, not the underlying facts or lifecycle.

- Goal/Task owner remains GoalStore/TaskStore.
- Evidence authenticity/integrity owner remains Evidence Ledger/BlobStore + TaskEvidenceVerifier.
- semantic score owner remains the frozen scorer/judge protocol.
- trace verdict owner remains the selected eval scenario/verdict implementation.
- runtime identity/config owner remains Runtime Manifest/EffectiveConfig/IdentityReport.
- architecture-submission policy owner remains A.5 declaration/review workflow.

No Envelope-owned semantic cache, status store, task ledger, verdict ledger, or second runtime manifest is permitted in v0.1.

### G3 — Model evidence/veto/recovery exit

v0.1 does not refuse actions, so no veto is required. Every displayed fact carries the owner and source reference. `unknown` is explicit. Recovery/inspection uses the existing owner path rather than an Envelope-specific override.

If a future Envelope becomes blocking, that future controller must separately define the exact refusal evidence and model/user recovery route.

### G4 — Rollback / verification

Rollback for this design is deletion/ignoring of the view/document; no runtime behavior changes.

A future implementation must prove at minimum:

- owner facts are byte/value-preserving projections;
- missing owners stay `unknown`;
- no SCORE becomes HARD without a frozen policy;
- no DIAGNOSTIC gets an implicit threshold;
- no global `qualified` result appears before a separately authorized/wired policy;
- disabling/removing Envelope leaves all existing owners and model-visible runtime behavior unchanged.

---

## 9. Explicitly rejected v0.1 shortcuts

### 9.1 Global `redundant_ratio > X => fail`

Rejected. Existing S1/C1 keeps unnecessary verification orthogonal to task success, while S2 only uses it inside a frozen, comparator-based, anchor-scoped policy. A global threshold would convert a strategy metric into Harness authority without evidence.

### 9.2 “More than N steps => fail”

Rejected. Step count/round count can be diagnostic or part of a frozen task-specific protocol, but is not a universal proof of invalid reasoning.

### 9.3 Reimplement adjacent duplicate detection

Rejected under G2. `no_repeat_tool` already checks adjacent exact fingerprint repetition. Future trajectory work should start only from uncovered mechanical cases such as non-adjacent exact recurrence with no intervening state change, terminal-after-close, stale-version action, or repeated non-idempotent side effect after successful receipt.

### 9.4 Treat Evidence integrity as semantic sufficiency

Rejected by the verifier's own contract (`src/llm_loop/introspection/task_evidence.py:1-6`).

### 9.5 Treat A.5 as Goal completion policy

Rejected. A.5 is explicitly a repository/submission architecture review gate (`docs/analysis/CONVERGENCE-DISPOSITION-20260910.md:657-705`).

---

## 10. Deterministic qualification plan for Step 3

No runner is added in this Step 1 document. The future deterministic matrix should freeze an exact source revision and verify only view correctness.

Minimum matrix:

1. **Source existence** — every matrix source path exists at the frozen revision.
2. **Anchor identity** — load-bearing source anchors still contain the expected symbol/contract text; line numbers are report metadata, symbol/content identity is the durable check.
3. **Owner uniqueness** — every substantive field has exactly one owner; no field owner is Envelope.
4. **Class completeness** — every field is exactly one of HARD / PREREGISTERED / SCORE / DIAGNOSTIC.
5. **Unknown preservation** — unavailable source maps to `unknown`, never pass/zero.
6. **No global aggregation** — `aggregate_verdict` stays `not_evaluated`.
7. **No threshold invention** — DIAGNOSTIC rows have no universal comparator/limit.
8. **Policy provenance** — every PREREGISTERED row carries a frozen policy/matrix/protocol ref.
9. **Scorer provenance** — every SCORE row carries scorer/judge version.
10. **Runtime identity provenance** — deployment fields come from existing manifest/receipt/build identity, not an Envelope recomputation.
11. **A.5 self-boundary** — any future blocking change to Envelope is detected as a control-machine change requiring its own G1–G4 declaration.

---

## 11. Step 1 exit criteria

Step 1 is complete when:

- the existing Goal/Task/Evidence/verdict/scorer/S2/runtime/A.5 mechanisms are mapped to exact source anchors;
- every proposed Envelope field is classified;
- no existing authority is reimplemented;
- Envelope is explicitly non-blocking and second-truth-store-free;
- uncovered gaps are described without implementing them;
- runtime/scorer behavior remains byte-for-byte untouched by this docs-only change.

The next phase, if separately continued, is Step 2/3: freeze the field list/classification and build a deterministic **read-only** matrix that proves the mapping can be consumed without semantic drift.
