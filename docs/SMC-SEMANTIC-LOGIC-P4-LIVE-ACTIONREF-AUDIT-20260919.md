# SMC Semantic Logic P4-LIVE ActionRef — Read-Only Architecture / Authority / Lifetime Audit

> Date: 2026-09-19
>
> Status: **READ-ONLY AUDIT COMPLETE / DESIGN ONLY / NO PRODUCTION WIRING**
>
> Audit base: `66f8d6147a67c4b439ca930149359674e500ba68`
>
> Qualified P4-FCR v0.2 evidence SHA-256: `7110c7c0a6305d1482a7bf92d2f5f690b3015ab538fa788b0b24c5e2e155ae5e`

## 1. Scope and ruling

This audit asks one question: after P4-FCR proved that the model can reliably declare short opaque ActionRefs, what mechanical contracts are still required before an ActionRef may reach a real Browser mutation?

The answer is **not** to replace the existing Browser executor. The current GroundingRef -> typed compiler -> version guard -> single-dispatch -> receipt chain already contains most of the hard safety mechanisms. The narrow P4-LIVE design is an ActionRef alias/binding layer in front of that chain, plus three missing execution-integrity links:

1. durable production ownership/lifetime for ActionRefs;
2. exact Browser target identity binding from observation through physical dispatch;
3. durable outer tool-execution provenance linking ActionRef to the existing Browser ActionReceipt.

No production source was modified during this audit. No Browser action, model request, deploy, restart, merge, or P4-LIVE execution occurred.

## 2. Existing production primitives that should be reused

| Boundary | Current mechanism | Audit ruling |
|---|---|---|
| Session ownership | Browser snapshots and receipts are partitioned by session hash | **REUSE** |
| Observation integrity | Immutable snapshot bundles carry SHA-256 integrity and TTL | **REUSE** |
| Runtime identity | perception store has runtime generation + runtime nonce for session-state recovery | **REUSE + bind into ActionRef** |
| Page/document lineage | CDP target id -> page token; loader id -> document generation; frame generations tracked | **REUSE** |
| Exact hydration | `BrowserPerceptionStore.hydrate()` resolves only exact retained GroundingRefs | **REUSE** |
| Stale/changed target guard | `assess_version_precondition()` compares exact expected vs fresh pre-dispatch observation, without refresh/rebind | **REUSE** |
| Stable physical object identity | dispatch resolves only stable captured physical identity; unstable snapshot-local AX identities reject | **REUSE** |
| Duplicate mutation prevention | deterministic inner `action_id` + `O_EXCL` reservation | **REUSE** |
| Run ownership | ToolExecutionJournal effect binding + SessionStore run-generation authority | **REUSE, mandatory for ActionRef path** |
| Timeout/cancel late worker | effect capability is revoked before timeout/cancel can return; late mutation fails closed | **REUSE** |
| Crash-safe outer execution | declared -> started -> finished -> receipt_committed WAL; unknown executions are never auto-replayed | **REUSE** |
| Mutation retry discipline | actuator and BrowserActionAdapter perform one dispatch and never auto-retry/rebind | **REUSE** |
| Browser target no-rebind after binding | capture host and actuator reject disappearance / target or websocket identity change | **REUSE but close first-bind gap** |
| Workspace transition | workspace switching is blocked while any run is active | **REUSE + ActionRef defense-in-depth binding** |

Selected current Browser action/version/WAL/CDP focused test suites passed on the exact audit base.

## 3. Material gaps before P4-LIVE

### G1 — ActionRef exists only in qualification code

The qualified `ActionRefBindingStore` is in-memory and qualification-only. Production has no durable ActionRef issuer/store/resolver and no model-visible ActionRef issued by real Browser perception.

**Required:** a versioned durable mechanical binding store. It must be independent of task semantics and must never search, rank, guess, substitute, or choose a target.

### G2 — FCR binding authority is too weak for live mutation

The FCR record binds session, a static authority scope, version, kind, TTL, and hidden GroundingRef. Live mutation additionally needs exact current runtime ownership:

- workspace scope;
- origin run generation;
- Browser perception runtime generation/incarnation;
- exact Browser page target identity;
- exact source snapshot / scope lineage;
- durable execution provenance when mutation is attempted.

**Ruling:** P4-LIVE ActionRefs are **run-bound aliases**, not durable cross-run capabilities. A new run must re-observe/reissue ActionRefs.

### G3 — capture host and actuator can independently first-bind different pages

`CdpReadOnlyBrowserHost` and `CdpBrowserMutationActuator` are separate objects. When `browser_perception_target_id` is empty, each independently binds the sole page at its first use.

A dangerous race therefore exists in principle:

1. perception observes target A;
2. A disappears before the mutation actuator has ever bound;
3. exactly one target B remains;
4. the actuator first-binds B.

The semantic version guard protects observation lineage but does not mechanically pass the exact observed CDP target identity into the actuator as a dispatch precondition.

**Required:** ActionRef mutation must never choose a Browser target at dispatch time. The exact target identity observed by perception must be verified against the actuator before the physical commit. P4-LIVE canary requires an explicit non-empty target id.

### G4 — no durable bridge from ToolExecutionJournal to Browser ActionReceipt

The outer WAL knows `execution_id`, `tool_call_id`, workspace, session, and origin run generation. BrowserActionReceipt knows `action_id`, scope/version, dispatch grounding, and before/after observation. The current Browser path does not durably join these identities before physical dispatch.

If a process fails after Browser dispatch but before the outer `finished` fact, WAL correctly reports `started_outcome_unknown` and never replays — safe, but incomplete for causality.

**Required:** before physical dispatch, persist an immutable execution-binding record joining:

`execution_id + tool_call_id + origin_run_generation + workspace_scope + action_ref + binding_digest + grounding_ref + action_id + expected_version + browser_target_identity`.

Recovery may then correlate the exact Browser receipt. It must still never auto-replay.

### G5 — direct calls without ToolExecutionJournal binding retain legacy mutation authority

`current_effect_mutation_authority()` intentionally returns true for legacy/direct callers when no effect binding exists.

That compatibility behavior should remain unchanged for old tools, but **new ActionRef mutation tools must require a live ToolExecutionJournal effect binding** and reject direct/unbound model mutation.

### G6 — legacy Browser mutation tools would bypass an ActionRef canary

With Browser mutation enabled, production currently registers:

- `browser_action`;
- `browser_semantic_execute`;
- `browser_semantic_operation`.

`browser_semantic_operation` can itself recapture and exact-unique-match kind/role/name to obtain a GroundingRef. That is a legitimate existing capability, but it would invalidate a P4-LIVE ActionRef treatment if visible in the same canary.

The main LoopEngine provider projection starts from the full registry and does not currently apply `current_tool_discovery_scope`; that scope is explicitly honored by subagent projection and discovery, not the main provider surface.

**Required:** the P4-LIVE canary must freeze the exact provider-visible Browser mutation subset to the five ActionRef typed mutation tools. The three legacy mutation tools must be absent both from provider schemas and from schema discovery for that canary execution domain.

### G7 — Browser stores are data-dir global, not workspace-partitioned

Workspace transitions already fail closed while a run is active, and sessions are workspace-partitioned. Browser perception/receipt roots, however, are under global `data_dir` and rely primarily on session fencing.

**Required:** bind the current canonical workspace identity into each ActionRef and each ActionRef execution-binding record as defense in depth. A workspace mismatch rejects before hydration/dispatch.

## 4. Authority split

### Model owns

- which observed target to act on;
- which verb to invoke;
- semantic argument values such as text, select value, URL, or scroll amount;
- whether to re-observe after a rejection;
- whether observed receipts/effects satisfy the user's task.

### Program owns only mechanical hard boundaries

- ActionRef issuance from an exact persisted observation;
- opaque-handle uniqueness and integrity;
- session/workspace/run/browser-target/runtime ownership;
- TTL/retention;
- exact ActionRef -> exact GroundingRef hydration;
- typed field/kind validation;
- version/scope/stable-physical-identity preconditions;
- durable execution binding;
- single-dispatch/idempotency fencing;
- timeout/cancellation revocation;
- receipt persistence and crash recovery without replay.

### Program must never

- search by name/selector/similarity on ActionRef failure;
- pick a successor or "latest" target;
- silently rebind a stale/expired/cross-scope ActionRef;
- normalize a wrong ActionRef into a valid one;
- replay a mutation whose outcome is unknown;
- decide semantic task completion.

## 5. Minimal production change surface for a later phase

The audit recommends a narrow adapter, not a new Browser executor:

1. **ActionRef binding store/issuer/resolver** — durable mechanical alias records.
2. **Perception projection annotation** — after a snapshot is durably persisted, add ActionRefs to the model-visible page resource and mechanically dispatch-eligible stable objects. Canonical persisted GroundingRefs remain unchanged.
3. **Five typed ActionRef mutation tools** — click/fill/select/scroll/navigate. Each resolves only an exact ActionRef, then delegates the hidden GroundingRef to the existing `BrowserSemanticExecuteTool` compiler and `BrowserActionAdapter`.
4. **Execution-binding bridge** — persist outer execution provenance before the existing physical dispatch window.
5. **Exact Browser-target precondition** — the mutation actuator must verify the perception-bound target; no first-bind target selection in the ActionRef path.
6. **Canary tool-surface projection** — mechanically exclude legacy Browser mutation tools from the canary provider/discovery surface.

Existing GroundingRef tools remain untouched for rollback and independent compatibility. The later production candidate should default ActionRef mutation exposure to off until separately qualified.

## 6. Conclusion

P4-FCR v0.2 proved the model declaration problem. P4-LIVE is primarily an **execution ownership and causality** problem, not another model-selection problem.

The current code already has the correct executor safety core. Production work should therefore be limited to a thin ActionRef capability alias plus missing ownership/provenance/target-binding gates. Reimplementing dispatch, target selection, stale handling, retries, or task semantics would be both unnecessary and contrary to the LLM-first boundary.
