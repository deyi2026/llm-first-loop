# SMC Browser v0.6 — First-Call-Ready Interface Design — 2026-09-13

Status: **READ-ONLY DESIGN / NO PRODUCTION IMPLEMENTATION**

Baseline: `90833264` (`docs(browser): record semantic confirmatory ruling`)

## 0. Decision summary

v0.5 confirmatory did **not** show a broken Browser actuator or a return of the old scope/version bug. It showed a remaining **model-facing contract-shape problem**.

Recommended v0.6 sequence:

1. **v0.6-A — Semantic Predicate Compiler + typed wait surface**
   - remove `wait` from the model-facing `browser_perceive` action union;
   - add two read-only typed tools: `browser_wait_scope` and `browser_wait_object`;
   - let the model choose the semantic condition; let the program compile only redundant mechanical Predicate fields;
   - keep `browser_semantic_execute` unchanged during this experiment.
2. Re-run the same frozen three tasks × two repeats with the same local Ornith/runtime limits.
3. Only if v0.6-A passes its independent gate, start **v0.6-B — navigation FCR** as a separate experiment.
4. Cloud canary remains closed until a local repeat-stability gate passes.

Explicitly rejected for v0.6-A: auto snapshot/latest, automatic target selection, retry/replay, rebind, task-completion logic, dynamic tool routing/hiding, larger universal prompt, or increasing max rounds to hide interface friction.

---

## 1. Confirmatory evidence that drives this design

The treatment-only v0.5 matrix was mechanically healthy:

- 6/6 rows mechanically complete;
- exact provider surface 6/6;
- semantic_execute adoption 6/6;
- no model fallback / no SecurityAgent;
- real navigate `ok` in 6/6;
- old scope/version blockers = 0;
- automatic retry = 0.

But task success was only 3/6, with every task exactly 1/2:

- `click_commit`: 1/2;
- `fill_submit`: 1/2;
- `delayed_wait`: 1/2.

All three failures consumed the frozen 12 rounds and never reached the final required object action.

Observable FCR facts across the same six rows:

| Observable call shape | Total | Successful rows | Failed rows |
|---|---:|---:|---:|
| initial navigate with URL placed in `target_ref` | 6 | 3 | 3 |
| `snapshot` carrying a `predicate` that runtime silently ignores | 9 | 2 | 7 |
| `wait` missing a structured Predicate | 4 | 1 | 3 |
| scope Predicate with `target != scope_ref` | 3 | 0 | 3 |
| invalid wait `interval_ms` | 0 | 0 | 0 |
| hydrate missing `grounding_ref` | 1 | 0 | 1 |

The seven wait failures are exactly:

- `predicate must be a structured object`: 4;
- `scope predicate target must equal its exact scope_ref`: 3.

This is correlation on a six-run local sample, not proof that wait failure is the sole cause of task failure. It is nevertheless load-bearing evidence because **all seven failures map to fields that are mechanically derivable or structurally expressible**.

---

## 2. Root cause A — `browser_perceive` is a schema superset, not an action-discriminated contract

Current model-facing shape is one tool with:

```text
action = snapshot | hydrate | diff | wait
properties = projection_limit + grounding_ref + from_version + to_version
             + predicate + timeout_ms + interval_ms
required = action
```

The lazy schema therefore says only `action` is universally required. It cannot express:

- `wait` requires predicate + timeout + interval;
- `hydrate` requires grounding_ref;
- `diff` requires from_version + to_version;
- `snapshot` must not carry predicate / grounding_ref / diff fields.

Runtime dispatch also currently reads only the fields relevant to the chosen action and does not reject all irrelevant fields. As a result, a call such as:

```text
snapshot(action=snapshot, predicate=...)
```

can return success while the Predicate is ignored. v0.5 emitted this shape nine times.

This is worse than an explicit validation error: it consumes a round while giving the model a successful observation that does not mean the requested condition was evaluated.

### Lazy-schema constraint

The current lazy skeleton preserves only a reviewed subset:

```text
type / enum / properties / items / required / minimum / maximum / maxLength
```

It does **not** currently carry conditional JSON Schema constructs such as `oneOf`, `if/then`, or `const`, nor unreviewed `pattern` constraints. Therefore “fix the single tool with a conditional schema” is not a local Browser-only change; it would require a broader provider-compatibility and prefix-contract change.

For v0.6, that is unnecessary risk.

---

## 3. Root cause B — Predicate still makes the model maintain redundant mechanical fields

`browser_semantic_execute` already follows the correct LLM-First split:

```text
model owns: verb + selected exact ref + semantic args
program derives: schema/domain/scope/target/version/action identity/mechanical constants
```

The current Browser Predicate does not yet have the analogous compiler. The model must submit all seven fields:

```text
schema
domain
scope_ref
target
property
operator
value
```

But several of these are not semantic choices:

- `schema = smc.predicate.v0.1` is fixed;
- `domain = browser` is fixed;
- for a scope Predicate, `target` **must equal** `scope_ref`;
- for an object Predicate, the object Semantic ID and its `scope_ref` are both derivable from an exact object GroundingRef.

The three observed `target != scope_ref` failures are therefore the Predicate equivalent of the old full SemanticAction problem: the model is manually maintaining a relationship the runtime already knows mechanically.

### LLM-First boundary

A Predicate compiler is valid under the project philosophy because it does **not** choose:

- which object/scope matters;
- which property to inspect;
- operator;
- expected value;
- whether waiting is useful for the task;
- whether a satisfied Predicate completes the task.

It only compiles identity and fixed schema relations after the model has made those choices.

---

## 4. Recommended v0.6-A interface

### 4.1 Keep `browser_perceive`, but narrow it to non-wait observation

Model-facing actions:

```text
snapshot | hydrate | diff
```

`predicate`, `timeout_ms`, and `interval_ms` disappear from this tool's provider schema.

Future implementation should also apply branch-local exact-key validation so irrelevant parameters are rejected mechanically rather than silently ignored. This is a protocol-hardening fact, not semantic routing.

Do **not** split snapshot/hydrate/diff into three tools in v0.6-A. The current evidence is dominated by wait ambiguity; a full read-only tool explosion would widen the intervention before evidence requires it.

### 4.2 Add `browser_wait_scope`

Proposed model-owned fields:

```text
scope_ref
property       = url | document_ready_state | object_count
operator
value
timeout_ms
interval_ms
```

Program mechanically compiles:

```text
schema   = smc.predicate.v0.1
domain   = browser
target   = scope_ref
```

Then it delegates to the existing read-only polling/evaluation path unchanged.

Important: `scope_ref` is still selected by the model from a real observation. If that scope is no longer observed in later samples, the existing evaluator returns `indeterminate / scope_not_observed`; the compiler must not replace it with a newer scope.

### 4.3 Add `browser_wait_object`

Proposed model-owned fields:

```text
object_ref      # exact SemanticObject.grounding_ref from an observation
property        = exists | enabled | visible | checked | selected |
                  expanded | focused | editable | name | value_text
operator
value
timeout_ms
interval_ms
```

Program steps are mechanical:

1. hydrate exactly the supplied `object_ref` in the current session;
2. reject unavailable / expired / unauthorized / wrong projection;
3. extract `semantic_object.id` and `semantic_object.scope_ref`;
4. compile fixed `schema/domain` + canonical `scope_ref/target`;
5. poll using the existing Predicate evaluator.

No fallback object lookup, no name matching, no rebind, no “closest” object, no automatic new snapshot selection.

### 4.4 Why two wait tools, not one generic `browser_wait`

A generic shape such as:

```text
subject_kind = scope | object
subject_ref
property
...
```

is smaller in tool count, but it reintroduces cross-field combinations the current lazy schema cannot structurally prohibit: for example `subject_kind=object + property=document_ready_state`.

Two typed tools let the provider-visible `property` enums themselves encode target kind. That structurally removes the exact class seen in v0.5 without needing `oneOf` or provider-specific schema behavior.

Parameter-schema cost is not a blocker: a read-only estimate using the current lazy JSON representation gives:

- current `browser_perceive` parameter schema: about 1201 serialized chars;
- `browser_perceive` without wait + typed scope/object wait parameter schemas: about 1218 chars total.

This `+17` figure excludes tool names/descriptions and is **only a schema-size comparison**, not a token or latency claim. It shows that typed separation need not imply a large parameter-schema expansion.

---

## 5. Navigation FCR: real problem, deliberately deferred to v0.6-B

In all 6/6 confirmatory runs, the first tool call was effectively:

```text
semantic_execute(
  verb=navigate,
  target_ref=<the user URL>,
  args={url: <the same URL>}
)
```

The tool correctly rejected it with `target_ref_unavailable:invalid_ref`, after which all six runs recovered by taking a snapshot.

This is a stable conceptual friction: natural user intent says “open this URL”, while the unified semantic tool uses one field named `target_ref` for both object GroundingRefs and page resource refs.

However this failure occurred in **every successful row as well as every failed row**. It is a fixed one-round tax, not the strongest discriminator for the 3/6 stability failure.

### Why not auto-snapshot for navigate

Current B-SPEC requires every mutation, including navigate, to carry a prior `expected_version`; dispatch then fresh-observes and validates the resource scope. An implementation that silently captures “whatever is current now” and uses that same fresh fact as its own precondition would effectively turn optimistic concurrency into implicit `latest`.

That would weaken a frozen safety semantic to improve a score and is rejected.

### v0.6-B candidate, only after v0.6-A qualifies

Test a structural split while keeping explicit prior observation:

```text
browser_navigate(resource_ref, url)
browser_object_execute(verb, object_ref, args)
```

The program continues to compile version/scope/action-id mechanically and still requires the exact previously observed resource/object ref. The model still chooses URL, object, verb, and semantic args.

This removes the dual meaning of `target_ref` and the navigate-specific nested `args={url}` shape without changing stale/version policy.

Do not combine this with v0.6-A in the first experiment. Otherwise a success cannot be attributed to wait-contract repair versus navigation-interface repair.

---

## 6. Alternatives not recommended as the first v0.6 intervention

| Option | Ruling | Reason |
|---|---|---|
| More compact prose on current Predicate | Reject as main fix | v0.4 already showed local prose helps but does not make correlated fields structural |
| Generic `browser_wait(subject_kind, subject_ref, ...)` | Hold | smaller surface, but target-kind/property cross-field mismatch remains |
| Conditional `oneOf/if/then` inside current perceive tool | Hold | current lazy transport drops these constructs; would widen provider compatibility work |
| Fully split snapshot/hydrate/diff/wait into 5 tools immediately | Defer | clean architecture, but larger intervention than current failure evidence requires |
| Auto snapshot / auto latest before navigate | Reject | weakens explicit version-precondition semantics |
| Hide mutation tools until snapshot exists | Reject | dynamic program-side routing/eligibility reduces model agency and changes current contract |
| Increase max_iterations to make failures finish | Reject as fix | can mask wasted-round FCR defects; may be tested later only as an independent capacity study |
| Universal prompt instructions | Reject | violates current governance and duplicates capability-local mechanical facts globally |

---

## 7. v0.6-A implementation contract to test later

No implementation is authorized by this document. If approved, TDD should freeze these properties before production edits:

### Mechanical/compiler tests

1. `browser_wait_scope` derives `schema/domain/target=scope_ref` exactly.
2. Scope property enum contains only the three current scope properties.
3. `browser_wait_object` accepts only exact object GroundingRef; it hydrates session-fenced identity and derives Semantic ID + scope.
4. Object property enum contains only current object properties.
5. Cross-session / expired / unknown / non-object refs fail before polling.
6. No alternate target lookup, fallback, rebind, latest-ref substitution, or automatic action retry.
7. Existing `satisfied / unsatisfied / indeterminate`, sampling, timeout, observer-error and completeness semantics remain unchanged.
8. `browser_perceive` no longer exposes wait/predicate/time fields; branch-irrelevant arguments do not silently succeed.
9. No Browser mutation path is callable from either wait tool.
10. Existing ActionReceipt/task-completion semantics are unchanged.

### Provider-surface tests

The real `lazy=True` surface must show, before any model request:

- scope/object wait as separate tool names;
- target-kind-specific `property` enums;
- all condition/time fields at top level and required;
- `interval_ms` 1..5000 and `timeout_ms` 1..60000 as machine bounds;
- no reliance on nested parameter descriptions or conditional JSON Schema constructs;
- no provider-specific rewrite for Ornith, GLM, MiniMax, or DeepSeek.

---

## 8. Pre-registered v0.6-A validation sequence

### Stage A0 — deterministic equivalence, no model

For fixed snapshot sequences, compare the compiled wait path with the existing canonical Predicate path:

- scope satisfied / unsatisfied / indeterminate;
- object satisfied / unsatisfied / indeterminate;
- timeout and sample_count;
- observer errors;
- scope change / target missing / incomplete coverage.

Valid semantic choices must produce the same canonical Predicate and observation result. The new layer is allowed to remove model-owned redundant fields; it is not allowed to reinterpret the condition.

### Stage A1 — tiny real-model FCR smoke

Use the same Ornith and serial 8901. Freeze two read-only tasks before running:

- one scope-level wait;
- one object-level wait.

Primary observations:

- first wait call structurally complete;
- missing-Predicate failures = 0;
- scope-target mismatch failures = 0;
- `snapshot(predicate=...)` calls = 0;
- no mutation and no fallback.

This is an interface smoke, not task-generalization evidence.

### Stage A2 — same main confirmatory matrix

Re-run the exact v0.5 user prompts, fixture/oracles and runtime limits:

```text
click_commit × 2
fill_submit × 2
delayed_wait × 2
```

No increased rounds; no replay after failure.

Proposed independent gate:

- 6/6 mechanically complete;
- exact intended surface 6/6;
- no fallback / SecurityAgent;
- SMC mutation adoption 6/6;
- external task oracle 6/6 and every task 2/2;
- every row has required navigate/object receipts;
- wait compiler/contract failures = 0;
- old scope/version blockers = 0;
- automatic retry = 0.

Still observe, but do **not** add post-hoc to this gate:

- initial invalid navigation ref calls;
- rounds/tools/tokens/cache/wall;
- get_tool_schema calls;
- non-scope/version rejected receipts.

If A2 fails, do not start navigation redesign or cloud canary in the same evidence set. First classify whether the remaining failure is wait, navigation FCR, object action, or unrelated model trajectory.

---

## 9. v0.6-B validation, conditional on A2 PASS

Freeze v0.6-A as baseline, then change only the navigation/object execution surface.

First run a small first-call A/B between:

- A: current unified `browser_semantic_execute(verb,target_ref,args)`;
- B: `browser_navigate(resource_ref,url)` + `browser_object_execute(...)`.

Measure whether URL-as-resource-ref / pre-snapshot invalid navigation is reduced without automatic observation or weaker stale checks.

Only after a positive micro result, rerun the same 3×2 task matrix with a new independent gate. Do not pool v0.6-A and v0.6-B results.

---

## 10. Cloud boundary

GLM / MiniMax / DeepSeek canary remains **closed** now.

It opens only after a local interface package reaches its own pre-registered repeat-stability gate. The cloud experiment must reuse the same semantic tool contracts and Method text; provider-specific semantic rewrites would invalidate the architecture claim.

---

## 11. Final architecture ruling

The evidence now supports a symmetry principle:

```text
Semantic Action Compiler:
  model chooses action semantics
  program compiles mechanical action identity/version fields

Semantic Predicate Compiler:
  model chooses observation condition semantics
  program compiles mechanical predicate identity/scope fields
```

This is a narrower and more LLM-First correction than adding more instructions. It removes fields the model has no reason to invent while preserving the decisions the model is supposed to make.

The recommended next implementation checkpoint is therefore **v0.6-A typed wait compiler only**. Navigation FCR remains a documented second variable, not part of the first patch.

---

## 12. 2026-09-16 addendum — from First-Call-Ready to Model-Friendly Semantic Operation

The v0.6 FCR design remains valid as historical evidence and as the first local correction of redundant mechanical Predicate fields. Subsequent FC2 work showed that the same principle generalizes beyond typed wait: the main remaining problem is now **model-facing interaction amplification across the whole semantic-operation path**.

The current forward design is recorded in:

- `SMC-MODEL-FRIENDLY-SEMANTIC-OPERATION-DESIGN-v0.1-20260916.md`
- `SMC-MODEL-FRIENDLY-SEMANTIC-OPERATION-EXECUTION-PLAN-20260916.md`

The important extension is:

```text
FCR:
  Can the model express the first valid operation without learning the protocol by failure?

Model-Friendly Semantic Operation:
  After the model has made a semantic decision, how much additional model I/O is required
  before that already-decided intent is safely grounded, executed and mechanically verified?
```

New architecture concepts:

- **Model-Declared Execution Horizon**: program may batch only steps the model has already declared;
- **Semantic Decision Boundary**: ambiguity, stale state, unknown outcome or undeclared structural transition returns control to the model;
- **Semantic Round-Trip Amplification**: measure model interaction tax separately from internal capture/polling work;
- **Interface Tax**: remove mechanically derivable fields from the normal model path while preserving exact durable evidence.

This addendum does not retroactively change the v0.6 experiment result. It changes the recommended next research unit: run the MF-0 interface-tax audit before further production expansion.
