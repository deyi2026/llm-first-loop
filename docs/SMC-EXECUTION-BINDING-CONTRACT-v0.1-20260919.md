# SMC Execution Binding Contract v0.1

> Date: 2026-09-19
> Status: **FROZEN CANDIDATE / DETERMINISTIC CONTRACT / NON-PRODUCTION**
> Parent architecture: `SMC-AI-NATIVE-CONTROL-PLANE-v0.2-20260919.md`
> Adversarial review: `SMC-AI-NATIVE-CONTROL-PLANE-v0.2-GRILL2-RESULT-20260919.md`

---

## 0. Purpose

This contract defines the mechanical layer that maps an already-chosen SMC SemanticAction to an exact platform execution mechanism.

It does **not** define:

- task planning;
- target selection;
- semantic-verb selection;
- recovery strategy;
- task completion;
- provider permission authority;
- automatic semantic fallback.

The core invariant is:

> **The model chooses semantic meaning. Execution Binding preserves that meaning while removing physical precision burdens from the model.**

---

## 1. Contract objects

Execution Binding v0.1 freezes six mechanical envelopes:

1. `CapabilityManifestPage`
2. `ActionRefRecord`
3. `ExecutionBinding`
4. `InteractionContext`
5. `BindingDispatch`
6. `BindingReceipt`

These are **not** new SMC core semantic objects. They are runtime/adapter support contracts around the existing six SMC objects.

---

## 2. CapabilityManifestPage

### MUST

- identify provider/domain/scope;
- carry an immutable `manifest_revision`;
- declare deterministic ordering;
- expose typed capabilities as data;
- expose projection completeness;
- use revision-bound cursors;
- allow explicit mechanical filters;
- make unsupported/human-required classes representable.

### MUST NOT

- rank by task relevance;
- silently omit items while claiming completeness;
- continue a cursor across revisions;
- grant permission;
- turn every item into a new global provider-visible tool.

### Stable ordering

The default contract order is:

~~~text
(provider_id, target_kind, semantic_verb, capability_id)
~~~

A domain may declare another deterministic ordering in its profile.

---

## 3. ActionRefRecord

### Meaning

An ActionRef is a short opaque handle to an exact runtime binding record.

### v0.1 validity

~~~text
validity_class = observation_exact
~~~

### MUST bind

- session;
- device;
- domain;
- scope;
- SemanticObject id;
- observation;
- observed version;
- authority scope;
- exact grounding or exact provider object identity;
- integrity;
- retention deadline.

### TTL rule

`expires_at` is a **retention** deadline only.

An unexpired ActionRef can still be stale.

### MUST reject

- wrong session;
- wrong authority;
- integrity mismatch;
- expired retention;
- stale observation/version;
- unresolved identity.

### MUST NOT

- fuzzy rebind;
- recapture-and-reuse;
- silent successor issuance;
- mint permission.

---

## 4. ExecutionBinding

An ExecutionBinding states that a particular physical mechanism implements one already-declared semantic capability.

### Binding classes

~~~text
native_semantic
app_intent
native_api
accessibility_action
system_command
application_command
keyboard_shortcut
structured_keyboard
structured_pointer
structured_gesture
vision_grounded_input
~~~

### Equivalence class

Automatic selection is legal only among bindings with the same frozen:

- semantic verb;
- target kind/scope semantics;
- semantic argument contract;
- effective permission class;
- confirmation semantics;
- effect class;
- idempotency class;
- atomicity class;
- receipt obligations.

### Fallback rule

~~~text
fallback_policy = equivalent_only
~~~

No binding failure may cause silent switch to a semantically different action.

---

## 5. InteractionContext

This envelope contains only mechanically observable context needed by context-sensitive bindings.

Common fields:

- active application;
- active window;
- focused object;
- selection;
- input method;
- keyboard layout;
- modifier state;
- foreground scene;
- orientation;
- virtual keyboard state;
- system overlay state;
- lock state.

Each context has a version.

Bindings such as shortcut/keyboard/pointer/gesture MAY require exact context preconditions.

Direct semantic bindings SHOULD avoid unnecessary focus coupling.

---

## 6. BindingDispatch

BindingDispatch is created only after the model has selected:

- semantic target;
- semantic verb;
- semantic args.

It includes:

- ActionRef;
- capability_ref;
- binding_id;
- requested SemanticAction summary;
- expected observation/version;
- binding-specific context preconditions;
- current effective permission/confirmation requirements.

### Admission order

Before physical effect:

1. validate ActionRef integrity/session/retention;
2. validate exact identity/version;
3. validate capability revision;
4. validate current runtime/platform authority;
5. validate confirmation state;
6. validate binding-specific InteractionContext;
7. reserve effect scope if required;
8. dispatch once.

No step may rewrite semantic target/verb/args.

---

## 7. BindingReceipt

Every attempted dispatch produces an auditable receipt.

It records:

- requested action;
- effective action;
- whether user confirmation modified parameters;
- binding id/class;
- precondition results;
- dispatch status;
- before/after versions;
- before/after context facts where relevant;
- observed effects;
- boundary events;
- completeness;
- retry/attempt facts.

### Requested versus effective action

Normally:

~~~text
requested_action == effective_action
~~~

The v0.1 allowed exception is an explicitly authorized user confirmation surface that changes semantic parameters.

Then the receipt MUST preserve both values and identify the user confirmation provenance.

Compiler/runtime code may not create such a semantic delta itself.

---

## 8. Authority and confirmation

### Provider

Provider metadata may describe requirements.

It cannot:

- grant permission;
- waive permission;
- mark a protected action as unprotected;
- claim human confirmation occurred.

### Runtime/platform

Current authority is re-evaluated at dispatch.

Any stricter requirement from platform/runtime/enterprise policy remains effective.

### Protected interaction

When an action requires human-only protected interaction, the mechanical result is:

~~~text
human_required
~~~

not a coordinate/vision bypass.

---

## 9. Human and AI concurrency

### Human preemption

The human always retains physical control.

AI leases MUST NOT disable or suppress human input.

### Effect reservation

Runtime may reserve narrow programmatic effect scopes to prevent:

- duplicate dispatch;
- concurrent AI writers;
- same-object races.

### Context-sensitive actions

For shortcut/input actions:

~~~text
prepare exact context
→ revalidate exact context
→ single dispatch
~~~

If human/external interaction changes context before dispatch:

~~~text
reject: context_changed
~~~

No focus war, no automatic retry.

---

## 10. Cross-device identity

Local SemanticObject identity is not globally portable by default.

Optional provider metadata may carry:

~~~text
entity_namespace
entity_id
issuer
~~~

Two local objects may be linked only when authoritative issuer/provenance semantics support the link.

Name/path/content similarity never creates identity.

Cross-device entity lifecycle remains outside Execution Binding v0.1.

---

## 11. Deterministic conformance gates

### EB0 — Closed schema

All six envelopes are versioned and reject undeclared core fields.

### EB1 — ActionRef exactness

- TTL retained but version stale => reject.
- same exact observation/version => eligible.
- cross-session/tamper/expired => reject.

### EB2 — Manifest consistency

- deterministic order;
- no cursor crossing revision;
- partial projection is explicit;
- capability_ref is revision-bound.

### EB3 — Semantic equivalence

- same equivalence class => mechanical binding selection allowed;
- different semantic/effect/confirmation class => no automatic fallback.

### EB4 — Authority monotonicity

- provider cannot override runtime/platform deny;
- stricter confirmation requirement wins mechanically;
- protected human interaction remains human-required.

### EB5 — Context safety

- exact context passes;
- focus/window/context revision change rejects context-sensitive dispatch;
- context-insensitive direct semantic action is not rejected merely because focus changed.

### EB6 — Human preemption

- human context change invalidates pending physical-input dispatch;
- lease never blocks user control;
- already-dispatched effect settles by receipt, not fictional rollback.

### EB7 — Receipt honesty

- binding used is recorded;
- requested/effective action delta is zero unless explicitly user-confirmed;
- observed side effects are retained on failure/ambiguity.

### EB8 — Cross-device identity

- issuer-backed portable identity may link;
- similarity-only candidate may not link.

---

## 12. Non-goals of v0.1

This contract does not yet qualify:

- any production OS adapter;
- any OS permission prompt automation;
- global cross-device entity lifecycle;
- an `identity_continuous` ActionRef class;
- dynamic semantic fallback;
- task-aware capability ranking;
- model FCR of one generic act tool versus narrow typed tools;
- live user/AI co-control UX.

Those require separate evidence.

---

## 13. Frozen artifacts

The v0.1 deterministic package consists of:

- this contract;
- `SMC-EXECUTION-BINDING-SCHEMA-v0.1.json`;
- `tests/fixtures/smc_execution_binding_v01.json`;
- `tests/unit/test_smc_execution_binding_contract_v01.py`.

Passing these artifacts proves only deterministic contract coherence.

It does **not** prove live OS control quality or user safety.
