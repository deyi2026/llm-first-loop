# SMC Semantic Logic P4-LIVE ActionRef Protocol v0.1

> Date: 2026-09-19
>
> Status: **FROZEN DESIGN CANDIDATE / NO PRODUCTION IMPLEMENTATION / NO LIVE EXECUTION**
>
> Parent qualified result: `66f8d6147a67c4b439ca930149359674e500ba68`

## 1. Objective

P4-LIVE v0.1 defines the narrow contract required to carry the qualified P4-FCR ActionRef representation into a real Browser mutation without transferring semantic authority from the model to program code.

The intended flow is:

`exact Browser observation -> mechanical ActionRef issuance -> model chooses typed action + ActionRef + semantic args -> exact ActionRef resolution -> hidden exact GroundingRef -> existing BrowserSemanticExecute compiler -> existing stale/scope/physical-identity guard -> one Browser dispatch -> durable receipt/provenance`.

The ActionRef layer is an **opaque alias and capability fence**, not a target resolver.

## 2. Frozen architecture

### 2.1 Perception and issuance

The canonical Browser perception store remains unchanged and continues to persist full GroundingRefs.

After a snapshot is durably persisted, a future ActionRef issuer may mechanically annotate the **model-visible projection** with:

- one page/resource ActionRef;
- one object ActionRef only for objects whose existing grounding record has mechanically dispatch-eligible stable physical identity.

GroundingRefs remain canonical and may stay visible for read/hydrate workflows. The P4-LIVE mutation treatment, however, accepts only ActionRefs through the five typed mutation tools.

Issuance must be idempotent for the same exact binding fingerprint within one run: one binding -> one ActionRef. Handles must be opaque, collision-checked, and contain at least 128 bits of cryptographic randomness. The handle must not encode target names, selectors, URLs, GroundingRefs, session ids, or filesystem identities.

### 2.2 Model-facing mutation surface

Exactly five typed mutation contracts are defined:

- `browser_semantic_click(action_ref)`
- `browser_semantic_fill(action_ref, text, mode)`
- `browser_semantic_select(action_ref, value)`
- `browser_semantic_scroll(action_ref, delta_pages)`
- `browser_semantic_navigate(action_ref, url)`

The model owns the ActionRef selection, verb/tool selection, and semantic argument values.

For P4-LIVE canary, these five tools are the **only provider-visible Browser mutation tools**. The following existing tools must be absent from both provider schemas and discovery in the canary execution domain:

- `browser_action`
- `browser_semantic_execute`
- `browser_semantic_operation`

Read-only perception and typed wait tools may remain visible. Non-Browser tools are outside this protocol, but the exact Browser mutation subset must be mechanically testable.

### 2.3 Exact resolution

Resolution accepts only the exact ActionRef string declared by the model. It performs no capture, search, matching, ranking, normalization, retry, "latest" lookup, successor substitution, or target rebinding.

A successful resolution returns the one hidden GroundingRef already stored in the binding. That exact GroundingRef is then passed to the existing `BrowserSemanticExecuteTool` compiler. The existing GroundingRef compiler remains the canonical source of target id, scope, expected observation version, inner deterministic action id, and verb-specific SemanticAction fields.

## 3. ActionRef binding record

A production binding is versioned as `smc.browser_action_ref_binding.v0.1` and contains at least these hidden mechanical facts:

- `action_ref` — opaque model-visible handle;
- `binding_id` / canonical binding fingerprint;
- `domain=browser`;
- `target_kind` = `object|resource`;
- `owner_session_sha256`;
- `workspace_scope_sha256` — canonical current run workspace identity, including an explicit sentinel when no workspace is bound;
- `origin_run_generation_sha256`;
- `browser_runtime_generation`;
- `browser_runtime_nonce_sha256` or equivalent runtime-incarnation proof;
- `browser_target_id_sha256` derived from the observed CDP target;
- `observed_snapshot_id`;
- `scope_ref`;
- `semantic_object_id` for object bindings, or exact resource identity for page bindings;
- hidden exact `grounding_ref`;
- `issued_at_epoch`;
- `expires_at_epoch`;
- `source_snapshot_expires_at_epoch`;
- integrity algorithm + digest over the complete unsigned record.

The store is durable and session-fenced. Records are immutable after issuance.

## 4. Lifetime and invalidation

P4-LIVE ActionRefs are **run-bound**.

A binding is rejected before mutation if any of these is true:

1. handle missing/unknown/duplicate collision;
2. integrity mismatch;
3. session mismatch;
4. workspace identity mismatch;
5. origin run generation is no longer the current active run generation;
6. ToolExecutionJournal effect binding is absent, revoked, or belongs to a different session/run/workspace;
7. binding TTL expired;
8. source snapshot expired/unavailable;
9. Browser perception runtime incarnation changed;
10. expected target kind does not match the typed tool;
11. exact observed Browser target identity is not the target authorized for dispatch;
12. exact GroundingRef hydration is unavailable/unauthorized/expired;
13. the existing pre-dispatch version/scope/physical-identity guard reports stale or indeterminate.

`expires_at_epoch` must be no later than the source snapshot expiry. Run termination invalidates the ActionRef even if the persisted TTL has not elapsed.

A newer observation alone does **not** cause the resolver to find a newer target. The existing pre-dispatch guard decides mechanically whether the originally observed target is unchanged enough to execute. If not, the action rejects and the model may choose whether to re-observe.

## 5. Browser target identity contract

The observed CDP target is a hard execution precondition.

For the ActionRef mutation path:

- the perception snapshot's private page token / target id is part of the hidden binding;
- the fresh pre-dispatch observation must be on that same target;
- the mutation actuator must verify that exact target before its physical commit;
- the actuator must not independently select "the only page" at dispatch time;
- disappearance, replacement, websocket identity change, or target mismatch rejects with zero dispatch.

The initial P4-LIVE canary requires an explicit non-empty Browser target id. Auto-selection by sole-page cardinality is not qualified for ActionRef mutation.

## 6. Tool execution authority

A P4-LIVE ActionRef mutation is legal only inside a live ToolExecutionJournal effect binding.

The new ActionRef mutation layer must mechanically verify that the current binding exists and matches:

- current session;
- current active run generation;
- current workspace scope;
- current provider tool call / execution attempt.

Legacy direct/control-plane mutation compatibility is not changed by this protocol. The **new ActionRef path** simply refuses to dispatch without the stronger execution binding.

## 7. Durable execution binding and recovery

After ActionRef resolution and existing SemanticAction compilation, but before physical dispatch, persist an immutable `smc.browser_action_ref_execution_binding.v0.1` record joining:

- session/workspace/run identities;
- `execution_id`;
- provider `tool_call_id`;
- tool name;
- ActionRef;
- ActionRef binding digest;
- hidden exact GroundingRef or its privacy-safe exact digest plus recoverable store link;
- inner deterministic `action_id`;
- expected observation version;
- Browser target identity digest;
- prepared timestamp.

This record must be durable before the existing Browser physical commit window opens.

Recovery rules are purely mechanical:

- execution binding exists, no Browser reservation/running receipt -> no dispatch is proven; never auto-run;
- reservation exists but no running receipt -> dispatch did not begin; never auto-run;
- running receipt without terminal receipt -> outcome unknown; never replay;
- terminal Browser receipt exists -> correlate it to the exact execution binding and recover the outer tool receipt without executing again;
- outer `finished` sidecar/receipt exists -> existing ToolExecutionJournal recovery remains authoritative.

The inner `action_id` remains derived from the hydrated GroundingRef + verb + semantic args, **not** from the ActionRef handle. Different aliases can therefore never bypass single-dispatch deduplication for the same exact underlying request.

## 8. Fail-closed reason families

The future implementation must expose stable mechanical reason codes, including at least:

- `action_ref_unavailable`
- `action_ref_integrity_error`
- `action_ref_session_mismatch`
- `action_ref_workspace_mismatch`
- `action_ref_run_generation_mismatch`
- `action_ref_effect_binding_missing`
- `action_ref_effect_binding_revoked`
- `action_ref_expired`
- `action_ref_source_unavailable`
- `action_ref_browser_runtime_mismatch`
- `action_ref_browser_target_mismatch`
- `action_ref_kind_mismatch`
- `action_ref_grounding_unavailable`
- `action_ref_execution_binding_not_durable`

All are zero-dispatch failures. None authorizes automatic repair or retry.

## 9. Deterministic RED gates before any production candidate may qualify

The following tests must first exist and fail on the current base for the expected missing capability, then turn green only through the minimal ActionRef implementation:

| ID | RED contract |
|---|---|
| P4L-R01 | real perception projection issues high-entropy opaque ActionRefs only after snapshot persistence |
| P4L-R02 | exact ActionRef mechanically recovers the byte-identical hidden GroundingRef; no search/rebind |
| P4L-R03 | cross-session ActionRef rejects with zero Browser dispatch |
| P4L-R04 | cross-workspace ActionRef rejects with zero dispatch |
| P4L-R05 | old/new run-generation mismatch rejects; run termination invalidates outstanding ActionRefs |
| P4L-R06 | expired/source-expired ActionRef rejects |
| P4L-R07 | Browser runtime restart/incarnation mismatch rejects |
| P4L-R08 | wrong object/resource kind rejects |
| P4L-R09 | integrity-tampered binding rejects |
| P4L-R10 | new ActionRef mutation tool without exact ToolExecutionJournal effect binding rejects |
| P4L-R11 | revoked/timeout attempt cannot dispatch after timeout becomes visible |
| P4L-R12 | perception target A cannot dispatch through actuator target B, including the unbound-actuator first-bind race |
| P4L-R13 | legacy Browser mutation tools are absent from P4-LIVE provider projection and get_tool_schema discovery |
| P4L-R14 | exact same resolved GroundingRef+verb+args yields the same inner action_id and physically dispatches at most once |
| P4L-R15 | durable execution binding is written before dispatch and links execution_id/tool_call_id/ActionRef/GroundingRef/action_id |
| P4L-R16 | crash after execution-binding prepare but before Browser running receipt never dispatches on recovery |
| P4L-R17 | crash after Browser running receipt but before terminal receipt recovers as unknown and never replays |
| P4L-R18 | crash after terminal Browser receipt but before outer WAL finished/commit correlates and restores the exact receipt without replay |
| P4L-R19 | stale document/page generation or changed/absent/unstable target rejects via existing version guard |
| P4L-R20 | existing GroundingRef Browser path remains unchanged when ActionRef feature is disabled |

No RED may be satisfied by adding name matching, selector fallback, similarity matching, automatic re-observation, or semantic completion logic.

## 10. Frozen P4-LIVE canary matrix

P4-LIVE execution is **not authorized by this protocol freeze**. When separately authorized after production qualification, use a dedicated local deterministic Browser fixture/profile and an explicit target id.

### Success rows

- L01 navigate once using an issued resource ActionRef;
- L02 click once using an issued object ActionRef;
- L03 fill once;
- L04 select once;
- L05 scroll once.

Each must prove model declaration -> ActionRef binding -> hidden GroundingRef -> inner action_id -> exact target -> one physical effect -> receipt provenance.

### Zero-dispatch rejection rows

- L06 cross-session;
- L07 cross-workspace;
- L08 prior run generation;
- L09 expired binding;
- L10 Browser runtime restart;
- L11 wrong kind;
- L12 integrity corruption;
- L13 stale document/navigation generation;
- L14 target replacement before mutation actuator's first use;
- L15 effect binding absent/revoked;
- L16 duplicate exact declaration after one successful dispatch.

### Crash/ambiguity rows

- L17 stop after durable execution binding but before Browser running receipt;
- L18 stop after running receipt around dispatch ambiguity;
- L19 terminal Browser receipt exists but outer ToolExecutionJournal `finished` is missing;
- L20 actuator transport error after possible side effect: no replay, factual ambiguity preserved.

The matrix is serial. No row may be retried or substituted. Browser state is reset by an explicit fixture boundary between rows where isolation is required, never by an implicit retry.

## 11. P4-LIVE hard gate

A future live run is qualified only if all are true:

- success rows L01-L05: exact declared ActionRef, expected hidden GroundingRef, expected inner action_id, exact Browser target, and exactly one intended physical effect;
- rejection rows L06-L16: **zero unintended physical dispatch**;
- crash/ambiguity rows L17-L20: **zero automatic replay**, provenance remains mechanically attributable or explicitly unknown;
- duplicate exact request: at most one physical dispatch;
- legacy mutation Browser tools absent from canary provider/discovery surface;
- all ActionRef issuance/resolution records pass session/workspace/run/runtime/target/TTL/integrity checks;
- no program target search/guess/rebind/substitution;
- no semantic task-completion judgment;
- no unexpected Browser target/tab;
- all durable execution bridges and Browser receipts are internally consistent;
- existing GroundingRef path regression suite remains green;
- rollback is demonstrated before any stable promotion.

## 12. Rollback and deployment boundary

Future ActionRef exposure must be explicit opt-in and default-off through the existing runtime configuration authority, not a new ad-hoc direct environment read.

Rollback is mechanical:

1. disable/unregister the five ActionRef mutation tools and ActionRef projection annotation;
2. leave existing GroundingRef perception/execution code unchanged;
3. keep persisted ActionRef/receipt records as inert audit evidence until retention cleanup;
4. restart only the service(s) required by the separately approved canary plan;
5. never require 8901 model restart merely to disable ActionRef Browser wiring.

No merge to main, deployment, restart, or Browser action is part of this protocol phase.

## 13. Non-claims

This protocol does **not** claim:

- that production ActionRef code exists;
- that the exact P4-LIVE RED tests have been implemented;
- that any P4-LIVE Browser mutation has executed;
- that ActionRef should replace all GroundingRef read/hydration surfaces;
- that `browser_semantic_operation` should be deleted;
- that direct/control-plane legacy mutation behavior should be globally changed;
- that a successful mechanical receipt means the user's task is semantically complete.

The next phase, if authorized, begins with deterministic RED tests and the narrowest production implementation only. It must stop again before the first P4-LIVE Browser mutation.
