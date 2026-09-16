# SMC Browser MF-5.3 — Read-Only Architecture Audit — 2026-09-16

Status: **READ-ONLY AUDIT COMPLETE / NO PRODUCTION CHANGE**

Semantic evidence anchor: `deb19f17ff916d5733727d94238b40fd09b5923e`

Primary prior result: `docs/SMC-BROWSER-COGNITION-PRESERVING-ACTUATION-MF5.2-v0.2-RESULT-20260916.md`

## 1. Audit question

MF-5.2 established that cognition-preserving syntax alone is not enough. Under an intentionally operate-only model surface, Ornith completed only 3/6 tasks; 16/18 contract failures came from trying to express page/document observation through an object-only target contract, and one repeat failed with zero protocol repair but repeated valid `target_not_found` probes.

MF-5.3 therefore audits four architecture questions without changing production code:

1. can existing `browser_perceive` be the model's natural read-only “eye”;
2. should one already-decided action use a direct single-action wire instead of mandatory `steps:[single]`;
3. where page/scope wait belongs and how it stays exact/fail-closed;
4. when post-action compact delta is enough, when exact hydrate is enough, and when a fresh full perception is mechanically required.

No live mutation qualification belongs to this phase.

---

## 2. Evidence base

Read-only source audit used the exact committed semantic workline and the frozen MF-5.2 evidence.

Authoritative implementation paths:

- `src/llm_loop/tools/builtin/browser_perceive.py`
- `src/llm_loop/browser/perception.py`
- `src/llm_loop/tools/builtin/browser_wait.py`
- `src/llm_loop/tools/builtin/browser_semantic_operation.py`
- `src/llm_loop/tools/builtin/browser_semantic_execute.py`
- `src/llm_loop/browser/action.py`
- `src/llm_loop/browser/method_card.py`
- `src/llm_loop/tools/registry.py`
- `src/llm_loop/factory.py`

Measured MF-5.2 facts retained unchanged:

- 53 semantic-operation calls;
- 52 valid single-action calls;
- 0 valid multi-action calls;
- 18 contract failures, 16 `short_target_fields_mismatch`;
- 14 valid-but-halted `target_not_found` calls;
- `delayed_wait-r2`: 0 protocol repair but TASK_FAIL;
- `click_commit-r2`: two successful commit clicks, oracle fail with `commit_count=2`;
- safety remained fail-closed: 0 auto retry, 0 hidden atomic calls, 0 runtime task-completion judgment, 0 undeclared-boundary continuation.

Important causal boundary: MF-5.2 intentionally exposed only `browser_semantic_operation`, `get_tool_schema`, and `read_evidence`. It explicitly hid `browser_perceive` and typed Browser wait tools. Therefore MF-5.2 is evidence that an **operate-only** surface is insufficient; it is not evidence that the existing perception implementation is defective.

---

## 3. Audit A — `browser_perceive` as the natural “eye”

### 3.1 Existing capability is already structurally suitable

`BrowserPerceiveTool` is read-only and session-fenced. Its current actions are:

- `snapshot`: capture the already host-bound page, DOM+AX -> `WorldSnapshot` + projected `SemanticObject`s;
- `hydrate`: exact hydration of a previously emitted grounding ref or semantic-operation receipt ref;
- `diff`: exact comparison of two persisted Browser snapshot IDs.

It exposes no URL navigation, selector, coordinates, model-supplied script, mutation, retry, fuzzy target choice, or latest/rebind behavior.

A snapshot already returns the facts needed for natural model reasoning:

- current `snapshot_id` / world version;
- exact document scope plus page/document/frame `scope_facts`;
- `resource_ref` for the bound page;
- projected semantic objects with exact grounding refs;
- `objects_ref` / `scope_facts_ref` for exact hydration;
- completeness and projection-completeness facts.

The underlying store is immutable, TTL-bounded, integrity checked and session fenced.

### 3.2 Production already has an eye; the model surface is fragmented

Factory registration is important:

- when Browser perception is enabled, LFL registers `browser_perceive` plus five narrow typed waits;
- mutation is a separate opt-in;
- when mutation is enabled, `browser_action`, `browser_semantic_execute`, and `browser_semantic_operation` are additionally registered.

So the current full Browser model surface can expose nine Browser tools. A static lazy-schema audit measured about **12,554 chars** across those nine tools.

The long-term model-facing architecture should not mirror those internal primitives one-for-one. They are good internal mechanical building blocks; they are too fragmented as the model's normal cognitive surface.

### 3.3 Current provider guidance is stale relative to Cognition-Preserving Actuation

The compact description for `browser_perceive` still embeds the historical Semantic Operation Method Card:

`Observe -> Ground -> Execute -> Receipt -> Re-observe/Verify`

and explicitly tells the model to use low-level `browser_semantic_execute`.

That guidance was appropriate for the earlier exact-ref qualification stage. It is now too procedural for the model-facing normal form. It encourages the model to think in protocol stages and implies mandatory re-observation, which conflicts with the newer rule:

> Preserve native task reasoning. Perception and actuation are capabilities the model invokes when its current semantic decision requires them; they are not a mandatory thought template.

The Method Card may remain as progressive-disclosure/internal methodology, but it should not remain load-bearing text in the default stable prefix of the future cognition-preserving surface.

### Audit A ruling

**Reuse `browser_perceive`; do not replace the perception engine.**

The next model-facing surface should make perception a first-class peer of actuation and hide the internal proliferation of typed wait/action primitives. The work is interface composition, not a new sensor stack.

---

## 4. Audit B — direct single-action normal form

### 4.1 Measured behavior is overwhelmingly singular

MF-5.2 produced 52 valid single-action semantic calls and zero valid multi-action calls.

The current provider wire still requires:

```json
{"steps":[{"do":"click","target":{"kind":"button","name":"Commit choice"}}]}
```

One measured failure used a singular object where the schema required a `steps` array, which is exactly the kind of wrapper/cardinality tax the model should not reason about.

### 4.2 Removing the wrapper is mainly a cognition improvement, not a token optimization

Static design-only measurements on the current candidate:

| Shape | Params chars / representative call |
|---|---:|
| current full operation params | 4,479 |
| hypothetical direct-root, same 7 variants | 4,322 |
| current click call | 76 |
| direct-root click call | 64 |
| current wait call | 100 |
| direct-root wait call | 88 |

The byte saving is modest. The architectural value is that one thought maps to one call without an artificial collection wrapper.

### 4.3 Wait should not stay inside the actuation grammar

If the two wait variants are removed from the operation surface and only mutation verbs remain, a hypothetical direct-root mutation schema is about **2,684 chars**. This is a much larger simplification because it removes a semantic category mismatch, not merely syntax.

The current compiler can already mechanically normalize one direct action into the existing single-clause executor without changing grounding/version/dispatch authority. That future normalization would be implementation work, not an architectural risk.

Root-level `oneOf` provider compatibility is **not qualified yet**. It must be tested before adoption. If a provider rejects root-level discriminated unions, a singular `action` object wrapper is a compatibility fallback, but it should not be preferred merely because it resembles existing code.

### Audit B ruling

For the next candidate, the model-facing normal form should be:

```text
one already-decided mutation -> one direct semantic action call
```

`steps:[...]` batching should not be the default provider surface. Keep batching internal or as a later optional escape hatch until real measured trajectories show a benefit. MDEH remains a capability, not a planning obligation.

---

## 5. Audit C — natural page/scope wait

### 5.1 The required mechanics already exist

Current typed Browser waits already support:

- exact scope URL condition;
- exact scope document readiness;
- exact scope object count;
- exact object state;
- exact object text.

They compile fixed mechanical facts into the qualified Predicate engine and do not mutate, retry, rebind, choose a fuzzy target, or decide task completion.

The current narrow tools are therefore strong **internal primitives**.

### 5.2 Their present model contract still leaks mechanical bookkeeping

The current narrow waits require the model to supply:

- exact `scope_ref` / `object_ref`;
- semantic condition;
- `timeout_ms`;
- `interval_ms`.

Polling interval is mechanical and should not be a model decision. Timeout should be optional unless the task has a real semantic deadline; a deterministic bounded runtime default is sufficient for the common case.

### 5.3 Page/scope wait does not belong in object actuation

`browser_semantic_operation` currently turns model-friendly wait targets into object identity targets requiring `kind + name`. That is the direct cause of most MF-5.2 contract failures when the model tried to express page/document observation.

Page readiness and URL are scope facts, not object mutations. They should live on the perception side.

### 5.4 Host-bound page aliases can remain exact without fuzzy target selection

`browser_perceive(snapshot)` already reads one page that the host backend has explicitly bound. A future page-level wait may therefore mechanically:

1. capture/bind the current host-bound page;
2. derive its exact page scope ref;
3. poll that **same** exact scope;
4. never switch to a different page/frame/latest target during the wait.

This is not semantic target selection; it is the same host binding already used by `snapshot`.

This special convenience must remain limited to the uniquely host-bound page. Arbitrary frames/scopes still require an exact ref from perception.

### 5.5 Object wait remains exact and should follow perception

For an already observed object, state/text wait should use its exact grounding ref. The model first perceives the object, then can wait for `enabled`, text change, etc.; the runtime exact-hydrates and polls the same identity.

A separate future capability would be required for “wait until an object with identity X appears” when no object exists in the seed observation. The current exact-object wait cannot truthfully do that because grounding fails before polling. MF-5.3 does not authorize solving that gap via fuzzy matching or retry loops.

### Audit C ruling

Treat wait as **read-only perception**, not actuation.

Long-term model surface should fold common typed waits behind perception while retaining existing typed wait classes as internal mechanical executors. Suggested model semantics:

```text
perceive snapshot current bound page
perceive wait page ready / URL condition
perceive wait exact observed object state/text
```

Runtime owns polling cadence and deterministic default timeout. The model owns the semantic condition and any task-specific deadline.

---

## 6. Audit D — compact delta vs exact hydrate vs explicit perception

### 6.1 Post-action observation already exists

`BrowserActionAdapter` already performs:

1. pre-action exact observation/version guard;
2. one mutation dispatch;
3. post-action capture;
4. a new persisted snapshot;
5. exact semantic diff from before -> after;
6. durable ActionReceipt.

The semantic-operation compact receipt already exposes:

- `world_version`;
- `diff_ref`;
- detected `boundary_events`;
- `receipt_ref`;
- `task_completion=not_evaluated`.

`browser_perceive(hydrate)` can exact-hydrate both the full operation receipt and the canonical `diff_ref` without another capture.

Therefore the architecture already supports three observation levels.

### 6.2 The current compact projection omits the facts needed to choose between those levels

The canonical diff contains mechanical facts such as:

- `comparable`;
- `scope_relation`;
- `completeness.complete` + reasons;
- `field_completeness`;
- created / removed / changed sets;
- exact `full_list_ref`.

But the compact semantic-operation receipt emits only the `diff_ref`, not those sufficiency facts.

At the same time, the ActionReceipt is intentionally `provisional=true` and currently leaves overall `completeness.complete=false` because boundary detection is non-exhaustive. Therefore “ActionReceipt complete?” cannot be used as a blanket rule for whether a new snapshot is required.

This creates a model-facing mismatch: the stable guidance says “snapshot again only if broader semantics/evidence incomplete/boundary changed,” but the compact result does not expose whether the local diff is comparable or complete.

### 6.3 Required three-level observation contract

The future surface should distinguish:

#### Level 1 — compact local delta

Returned automatically with actuation. It should expose only bounded mechanical facts, for example:

- post-capture succeeded / failed;
- resulting world version;
- diff ref;
- diff comparable yes/no;
- scope relation same/changed/unknown;
- diff completeness yes/no + compact reason codes;
- created/removed/changed counts or another small bounded summary;
- detected boundary events;
- exact receipt ref.

This is not a task-success judgment.

#### Level 2 — exact hydrate

Use `browser_perceive(hydrate)` on `diff_ref` or `receipt_ref` when the model needs exact local evidence already captured, but does not need a fresh broad page observation.

Hydration must never recapture, retry the mutation, choose a new target, or silently refresh a ref.

#### Level 3 — fresh full snapshot

Use `browser_perceive(snapshot)` when:

- the world/scope structurally changed (for example navigation/new document);
- post-action diff is missing, incomparable or incomplete;
- a detected boundary means grounding context changed;
- the model itself needs broader current-page semantics not present in the local delta.

The first three are mechanical evidence-integrity reasons. The last is a semantic decision owned by the model.

### 6.4 Duplicate mutation prevention rule

“Receipt ok != task complete” remains correct, but uncertainty about task completion must not imply “try the mutation again.”

If dispatch succeeded and task-level success is still unknown, the next move is **perception**, not automatic or speculative re-dispatch. This directly addresses the MF-5.2 `click_commit-r2` failure where a second successful click produced `commit_count=2`.

### Audit D ruling

Do not restore mandatory `re-observe after every action`. Also do not treat compact ack alone as semantic verification.

Use:

```text
operate -> compact local delta
          -> hydrate exact captured evidence when sufficient
          -> fresh perceive only at mechanical world-boundary/incomplete-evidence points
             or when the model semantically needs broader context
```

---

## 7. Proposed MF-5.3 target architecture (design only)

The long-term model-facing Browser surface should tend toward two capabilities:

### A. `perceive`

Owns read-only sensing and waiting:

- snapshot current host-bound page;
- exact hydrate of snapshot/object/diff/receipt refs;
- exact diff of persisted snapshots;
- page/scope readiness and URL wait;
- exact observed-object state/text wait.

It does not navigate or mutate.

### B. `operate`

Owns mutation only:

- navigate;
- click;
- set/append text;
- select;
- scroll.

Default normal form is one direct already-decided action. Runtime internally performs exact current grounding, version guard, one dispatch, post-capture and durable evidence.

No wait verb belongs in the normal actuation grammar.

Internal/debug tools may remain (`browser_wait_*`, `browser_action`, `browser_semantic_execute`) but should not all be normal provider-facing cognitive surface.

Static design-only size signal:

- current 9-tool Browser lazy surface: ~12,554 chars;
- current `perceive + semantic_operation`: ~6,239 chars;
- approximate two-tool surface with compact perception description + direct mutation-only operation: ~3,560 chars.

These numbers are architectural estimates, not qualification evidence. The goal is not minimum bytes; it is fewer semantic concepts and less protocol-induced reasoning.

---

## 8. Authority boundary

MF-5.3 does **not** relax any existing hard boundary.

Program may:

- capture the already host-bound page;
- build exact scope/object identities;
- mechanically bind the unique host-bound page for page-level wait;
- exact hydrate previously emitted refs;
- compile closed typed wait aliases;
- own bounded polling cadence/default timeout;
- exact-unique ground an explicitly named semantic object;
- version-check and single-dispatch;
- post-capture/diff/persist evidence;
- expose mechanical completeness/comparability/boundary facts.

Program may not:

- pick a fuzzy/best target;
- select among multiple pages/frames for the model;
- silently use latest/rebind when an exact ref is stale;
- infer task relevance or success;
- decide that a local delta semantically answers the user's task;
- automatically retry/replay a mutation;
- treat a failed wait/ground as permission to mutate;
- hide an evidence-integrity failure.

Model remains responsible for:

- what the task means;
- whether it needs broader perception;
- which semantic object/action is intended;
- what condition matters;
- whether observed evidence is sufficient for the task;
- whether the task is complete.

---

## 9. Recommended next phase after this audit

Do **not** implement all four changes at once.

Recommended MF-5.3 implementation order after human approval:

1. deterministic RED for the **two-capability cognitive contract**;
2. perception-side natural page/scope/object wait facade over existing typed waits, with runtime-owned interval/default timeout;
3. direct single-action mutation wire, mutation-only; keep old executor internal;
4. compact post-action delta sufficiency fields drawn from the already-persisted diff;
5. fresh treatment qualification where `perceive` and `operate` are both visible;
6. only after a hard PASS, independent repeat.

Pre-register diagnostics separately:

- full-snapshot calls;
- exact hydrate calls;
- page/scope/object wait calls;
- ground-probe amplification;
- duplicate successful mutation count;
- direct action contract repair;
- local-delta -> hydrate -> snapshot escalation distribution;
- rounds/tokens/cache as diagnostics, never correctness substitutes.

MF-6 remains deferred until a cognition-preserving treatment hard-passes.
