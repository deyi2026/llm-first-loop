# SMC AI-Native Control Plane v0.2 — Grill-2 Architecture Stress Result

> Date: 2026-09-19
> Status: **FROZEN DESIGN REVIEW / DOCS-ONLY**
> Parent design: `SMC-AI-NATIVE-CONTROL-PLANE-v0.2-20260919.md`
> Parent commit: `d92e63b20ed1b4d947a47f7f33f6d30e6cc95af3`
> Scope: five open architecture risks only. No production implementation, no provider-visible change, no P4-FCR treatment change.

---

## 1. Review method

The first v0.2 design intentionally left several questions open for experiments. Before freezing an Execution Binding contract, this review attacks the five questions most likely to invalidate the architecture:

1. ActionRef lifetime and stale semantics.
2. CapabilityManifest scale, paging and discovery.
3. Provider permissions, confirmation and user edits.
4. Concurrent human/AI ownership.
5. Cross-device identity.

The review uses the existing LLM-First authority split:

- the model owns semantic target/action/strategy/completion;
- Semantic Logic may only derive deterministic closure;
- Adapter owns physical observation/grounding/actuation primitives;
- Runtime owns permission, reservation, effect authority, idempotency and durable receipts.

The review does **not** optimize for convenience. When a choice would increase success rate by silently changing target, meaning, authority or provenance, the answer is fail-closed.

---

## 2. Grill A — What exactly makes an ActionRef valid?

### Attack

The earlier design says an ActionRef has an expiry time. That creates a dangerous ambiguity:

> If TTL has not expired, is the handle still fresh enough to execute?

For UI/OS state, the answer can be no within milliseconds:

- document reloaded;
- list item recycled;
- active tab changed;
- window focus moved;
- same visible label now names another object.

A TTL therefore cannot be a freshness proof.

### Ruling A1 — TTL is retention, never freshness

`expires_at` means only:

> the runtime promises to retain enough exact binding state to evaluate this handle until this time.

It does **not** mean:

> the world still matches the bound observation.

Action admission must separately validate exact scope/version/identity preconditions.

### Ruling A2 — v0.1 ActionRef is observation-exact by default

The initial contract uses:

~~~text
validity_class = observation_exact
~~~

An ActionRef binds:

~~~text
session
device
domain
scope
semantic_object_id
observation_ref
observed_version
authority_scope
integrity
retention deadline
~~~

If the relevant version scope no longer matches, the action is stale even when the handle is retained and cryptographically valid.

### Ruling A3 — Interaction context is a binding precondition, not universal ActionRef identity

A direct semantic API may not care which window has keyboard focus.

A shortcut absolutely does.

Therefore `active_window/focus/context_version` is **not** baked into every ActionRef. It belongs to the chosen ExecutionBinding's preconditions.

This prevents a focus change from unnecessarily invalidating a direct API action while still making shortcut/input actions fail closed.

### Ruling A4 — no hidden refresh

On stale/expired/unresolved:

- do not recapture and reuse the same ActionRef;
- do not find a similar object;
- do not issue a successor handle invisibly.

The model must observe again and choose from new facts.

### Result

**CLOSED for Execution Binding v0.1.**

Future experiments may qualify a narrower `identity_continuous` validity class, but it is explicitly out of v0.1.

---

## 3. Grill B — What happens when an App exposes thousands of capabilities?

### Attack

Turning every capability into a tool causes Tool Explosion.

Dumping one giant capability manifest causes:

- token explosion;
- long-prefix churn;
- incomplete provider projection;
- hidden truncation;
- unstable ordering.

Using semantic relevance ranking in the program would reduce token use, but would violate LLM-First by having the program decide which capabilities matter for the task.

### Ruling B1 — manifest discovery is revisioned data

Capability discovery returns a revision-bound page:

~~~text
manifest_ref
manifest_revision
provider_id
scope_ref
ordering
items
projection.complete
next_cursor
~~~

All pages in one enumeration MUST use the same `manifest_revision`.

### Ruling B2 — deterministic ordering

The initial ordering is mechanical:

~~~text
(provider_id, target_kind, semantic_verb, capability_id)
~~~

or another profile-declared deterministic key.

No:

- “best capability”;
- “likely useful”;
- task relevance score;
- model-inferred importance.

The model may explicitly request a mechanical filter such as:

~~~text
target_kind=document
verb_prefix=export
control_capability_class=DIRECT_SEMANTIC
~~~

### Ruling B3 — no silent cross-revision continuation

A cursor issued for manifest revision 41 cannot continue against revision 42.

Return:

~~~text
manifest_revision_changed
~~~

and let the model decide whether to restart enumeration.

### Ruling B4 — capability refs are revision-bound

A short `capability_ref` may be issued to reduce exact-string reproduction.

It is valid only for the exact provider/manifest revision and does not grant permission.

### Ruling B5 — completeness is explicit

Every page reports:

~~~text
projection.complete
next_cursor
returned_count
total_count   # nullable when the provider cannot mechanically know it
~~~

The absence of an item from a partial projection never proves that the capability does not exist.

### Result

**CLOSED for Execution Binding v0.1.**

The question “one generic act tool versus several narrow typed family tools” remains an FCR experiment, not a contract question.

---

## 4. Grill C — Can a Semantic Control Provider mint permission or weaken confirmation?

### Attack

A cooperative provider declares:

~~~text
permission_requirements = ["document.write"]
confirmation = "none"
~~~

But:

- OS policy may require stronger permission;
- enterprise policy may forbid the action;
- the current user grant may have been revoked;
- the platform may require a confirmation UI;
- a destructive action may require explicit human confirmation.

If Runtime trusts provider metadata as authority, SCP becomes a privilege escalation channel.

### Ruling C1 — provider metadata is descriptive, not authoritative

CapabilityManifest may describe required permissions, but it cannot:

- grant them;
- waive them;
- downgrade runtime/platform requirements;
- assert that a user confirmed something.

Runtime re-evaluates current authority immediately before dispatch.

### Ruling C2 — effective requirement is monotonic

Each authority layer may add constraints.

No lower layer may remove a stronger requirement from:

- platform;
- runtime policy;
- enterprise policy;
- current permission state;
- protected-interaction policy.

The compiled binding therefore carries the **effective** permission/confirmation preconditions and their provenance.

### Ruling C3 — confirmation can be semantic input

Modern platform confirmation surfaces can allow a person to edit parameters before confirming.

If the person changes:

~~~text
destination = folder_A
~~~

to:

~~~text
destination = folder_B
~~~

that is not a compiler rewrite.

It is a **user-authored semantic change**.

The receipt must preserve:

~~~text
requested_action
effective_action
user_modified_parameters
confirmation_ref
~~~

The execution may proceed only when the platform/runtime confirmation contract explicitly treats the confirmation surface as an authorized parameter-editing surface.

Otherwise changed parameters require rejection/replanning.

### Ruling C4 — protected interactions remain protected

Device unlock, biometric authentication, secure password entry, payment confirmation and OS security permission are not made automatable merely because an SCP exists.

Their capability remains `HUMAN_REQUIRED` unless the platform exposes an explicit legitimate machine-authorized flow.

### Evidence note

Apple App Intents currently exposes typed parameters, typed results and explicit confirmation APIs. The confirmation APIs are specifically intended for choices including destructive or unsafe actions, supporting the architectural separation between action declaration and user confirmation.

### Result

**CLOSED for Execution Binding v0.1.**

---

## 5. Grill D — Who owns the machine when the human and AI act at the same time?

### Attack

A global “AI control lock” is unacceptable:

- it can fight the user;
- it can make accessibility worse;
- it can turn focus management into a denial of control.

No locking at all is also unsafe:

- two AI actions can race;
- user focus changes can redirect shortcuts;
- a pending gesture can land in the wrong context.

### Ruling D1 — the human always has physical preemption

SMC MUST NOT create a lease that prevents the person from:

- moving pointer;
- typing;
- changing focus;
- switching apps;
- touching the screen;
- cancelling/taking over.

AI leases serialize **programmatic effect authority** only.

### Ruling D2 — leases are minimal-scope

Prefer:

~~~text
object/document effect reservation
~~~

over:

~~~text
whole desktop lock
~~~

Context-sensitive physical input may use a very short interaction lease covering:

~~~text
prepare context
revalidate context
single dispatch
~~~

It expires at the dispatch boundary.

### Ruling D3 — user interaction invalidates pending context-sensitive dispatch

Example:

1. AI focuses TextEdit document A.
2. User clicks Safari.
3. AI is about to send Cmd+S.

Correct result:

~~~text
rejected: context_changed
~~~

Incorrect result:

- stealing focus back repeatedly;
- sending Cmd+S to Safari;
- silently re-planning.

### Ruling D4 — already-dispatched effects settle; they are not rolled back by fiction

If the physical dispatch already happened:

- observe what changed;
- settle ActionReceipt honestly;
- never report “cancelled means nothing happened” unless mechanically proven;
- never replay non-idempotent action automatically.

### Ruling D5 — human intervention is evidence, not an error

Receipt/boundary events may record:

~~~text
human_interaction_observed
context_changed_by_external_actor
~~~

The model then decides what it means for the task.

### Result

**CLOSED for Execution Binding v0.1.**

---

## 6. Grill E — Is the “same document” on a Mac and phone the same SemanticObject?

### Attack

Suppose:

- a file named Report.docx exists on Mac;
- a Report.docx appears in a phone app;
- their content hashes happen to match;
- both show the same cloud account.

Can SMC merge their identity?

If yes by heuristic, cross-device actions can target the wrong object.

If no, cross-device workflows lose useful continuity.

### Ruling E1 — local SemanticObject identity remains domain/scope identity

SMC core does not claim that local objects on different devices are globally identical.

### Ruling E2 — portable entity identity requires an issuer

A provider may expose an optional portable identity such as:

~~~text
entity_namespace = "com.example.cloud.documents"
entity_id = "doc_123"
issuer = "provider_xyz"
~~~

The runtime may record that two local SemanticObjects refer to the same portable entity only when the issuer/provenance contract says so.

### Ruling E3 — similarity never proves cross-device identity

The following are evidence at most, not identity proof:

- same display name;
- same path suffix;
- same text;
- same image;
- same content hash;
- same position in a list;
- model belief.

### Ruling E4 — cross-device entity layer is not added to the six-object core in v0.1

Execution Binding v0.1 may carry optional externally issued entity metadata.

Cross-device synchronization, conflict resolution and global entity lifecycle belong to a future **Semantic Entity Layer**, unless implementation evidence proves they must move into core SMC.

### Result

**CLOSED for Execution Binding v0.1**, while the full cross-device Entity Layer remains future work.

---

## 7. Platform stress checks

### Windows

Current Microsoft UI Automation documentation continues to support the provider/client model: providers expose UI elements and control patterns; clients can retrieve properties and invoke functionality across process boundaries. UIA also permits custom control patterns, with Microsoft explicitly warning that custom patterns should be broadly specified rather than application-specific one-offs.

**Implication:** UIA can be an important structured binding surface, but SMC SCP should not simply generate one custom UIA pattern per App method.

### Android

Current Android AccessibilityService documentation states that services:

- are explicitly enabled by the user in device settings;
- can optionally retrieve active-window content;
- require declared capabilities for some operations such as gesture dispatch;
- have system-managed lifecycle.

Android also continues to impose background-activity/service restrictions outside the accessibility-specific lifecycle.

**Implication:** “Android adapter available” is not a blanket authority grant. Capability, current service state and platform restrictions remain runtime facts.

### iOS / Apple

UIKit Accessibility remains primarily an application-side surface for making app elements accessible. App Intents provides a stronger cooperative typed-action model with parameters, results and user confirmation.

**Implication:** production iOS SMC should be cooperative-provider/App-Intent-first, not based on an assumed generic cross-App AX client.

### Linux

AT-SPI exposes Action and focus-related state, supporting structured accessibility binding. Desktop/compositor/input differences remain profile-specific qualification work.

---

## 8. Final architecture changes from Grill-2

The parent v0.2 architecture remains valid with these refinements:

1. **ActionRef validity**
   - observation/version exact by default;
   - TTL is retention only;
   - interaction context stays binding-specific.

2. **Capability discovery**
   - revision-bound deterministic paging;
   - explicit completeness;
   - no relevance ranking;
   - optional short revision-bound capability_ref.

3. **Authority**
   - provider metadata cannot mint or weaken permission;
   - current runtime/platform authority rechecked at dispatch;
   - user-confirmed parameter edits are explicit co-authored semantic changes.

4. **Concurrency**
   - human always preempts;
   - AI leases serialize programmatic effects, never human control;
   - context-sensitive dispatch revalidates immediately before effect.

5. **Cross-device identity**
   - no heuristic merge;
   - issuer-scoped portable entity identity is optional evidence;
   - global entity lifecycle remains outside core SMC v0.1.

These rulings are sufficient to freeze a first deterministic Execution Binding contract/schema/fixture set without entering OS production implementation.
