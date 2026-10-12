# SMC Browser MF-5.3.2 Post-Qualification Read-Only Audit

Date: 2026-09-16
Baseline closure: `1cd2b246a557b98b31d78f2d8c7769ff2e8de770`
Production implementation anchor: `05d0f36c7202a8c183a517813815f6ef83f2cfe4`
Status: **READ-ONLY AUDIT COMPLETE — NO PRODUCTION/TEST CHANGE**

## 1. Scope and hard boundaries

This audit answers two questions left by the formal MF-5.3.2 measured result:

1. Why does first-call Browser capability routing still send navigation-shaped requests to `browser_perceive` after the peer hand was renamed to `browser_operate`?
2. Why can a task-correct mutation spend many more rounds/tokens verifying success and, in MF532 Row2, hit the frozen 240s worker timeout after the real `save_code` event already happened?

This phase intentionally does **not**:

- edit `src/` or `tests/`;
- create deterministic RED yet;
- run another model row;
- change prompts, max iterations, worker timeout, evidence budget or Gate;
- add fuzzy/best-match target repair, automatic mutation retry/replay, task-completion heuristics or navigation to Perceive;
- enter MF-6;
- push, merge, deploy or restart services.

The purpose is to separate the next two corrections before any implementation.

## 2. Authoritative evidence set

The audit reuses committed/frozen evidence only:

- MF-5.3.1 measured identity:
  `evals/browser_smc_cognition_preserving_actuation_mf531/results/MF531-ORNITH-v0.1-MEASURED-05f17151`
- MF-5.3.2 valid measured identity:
  `evals/browser_smc_cognition_preserving_actuation_mf532/results/MF532-ORNITH-v0.1-MEASURED2-5dffb6b3`
- MF-5.3.2 formal result:
  `docs/SMC-BROWSER-COGNITION-PRESERVING-MF5.3.2-v0.1-RESULT-20260916.md`
- current Browser perception/operation implementation at the closure commit.

No failed row was replayed and no new model output was generated for this audit.

---

# Part A — residual capability routing

## 3. First Browser call reconstruction

The first Browser call is especially useful for attribution because MF-5.3.2B projection ordering has not executed yet. B can only affect a model after a snapshot result exists; therefore **B cannot cause or repair the first Browser call**.

### 3.1 MF-5.3.1

| Row | First Browser call | Result |
|---|---|---|
| click_commit r1 | `browser_semantic_operation(do=navigate,url)` | valid |
| fill_submit r1 | `browser_perceive(action=navigate,url)` | failure |
| delayed_wait r1 | `browser_perceive(action=snapshot,url)` | failure |
| delayed_wait r2 | `browser_semantic_operation(do=navigate,url)` | valid |
| fill_submit r2 | `browser_perceive(action=navigate,url)` | failure |
| click_commit r2 | `browser_semantic_operation(do=navigate,url)` | valid |

First-call contract-valid: **3/6**.

### 3.2 MF-5.3.2

| Row | First Browser call | Result |
|---|---|---|
| click_commit r1 | `browser_perceive(action=snapshot,url)` | failure |
| fill_submit r1 | `browser_operate(do=navigate,url)` | valid in raw event stream; worker later timed out |
| delayed_wait r1 | `browser_operate(do=navigate,url)` | valid |
| delayed_wait r2 | `browser_perceive(action=navigate,url)` | failure |
| fill_submit r2 | `browser_perceive(action=navigate,url)` | failure |
| click_commit r2 | `browser_perceive(action=snapshot,url)` | failure |

Frozen Gate reports 1/6 because the timeout row has no final worker metrics. Raw event reconstruction yields **2/6**.

### 3.3 Ruling on MF-5.3.2A

The A rename was deterministic-safe, but the live treatment provides **no evidence that name-only peer identity solved routing**. The measured first-call result did not improve from MF531 3/6 to MF532 raw 2/6.

This is not a claim that the rename made the model worse; six rows are too small and local generation can vary. It is a narrower and stronger statement:

> **`browser_semantic_operation` → `browser_operate` is insufficient as the routing correction.**

Because the first call precedes any B projection, this conclusion is not confounded by MF-5.3.2B.

## 4. Actual provider tool order

The measured surface report sorts names for presentation, so it cannot establish wire order. Runtime `tool_reachability.jsonl` does.

MF531 provider order:

```text
read_evidence
browser_perceive
browser_semantic_operation
get_tool_schema
```

MF532 provider order:

```text
read_evidence
browser_perceive
browser_operate
get_tool_schema
```

`ToolRegistry.schemas()` preserves registry insertion order, and `_project_tool_schemas_for_round()` removes mechanically unavailable tools without reordering the survivors.

Therefore the eye is provider-visible before the hand in both measured identities. This is a real stable-prefix fact, but **tool order alone is not proven to be the causal defect**. Treat order as a secondary experimental variable, not the first production fix.

## 5. Stronger observed affordance collision: destination URL vs observed URL

Current lazy provider schemas are similar in serialized size:

- `browser_perceive`: ~3,315 chars; compact description 216 chars;
- `browser_operate`: ~3,359 chars; compact description 207 chars.

So the hand is not simply hidden by a dramatically smaller or missing schema.

However, Perceive's compatibility shape contains a shallow union of all action fields in addition to its closed `oneOf` branches. The top-level Perceive properties therefore expose a literal `url` field even though that field is legal only for `action=wait + kind=page_url`.

Mechanically observed Perceive lazy schema characteristics:

- `url` appears repeatedly in the serialized schema;
- `page_url` wait exposes `{action,kind,match,url,within_ms}`;
- compact prose says URL waiting belongs to Perceive and also says Perceive does not navigate;
- the closed action enum does **not** include `navigate`.

Operate separately exposes:

```text
do=navigate + url=<destination>
```

All four MF532 routing repairs are exactly destination-URL cross-bindings:

- two `action=navigate + url` calls sent to Perceive;
- two `action=snapshot + url` calls sent to Perceive.

This is stronger evidence than the rename hypothesis:

> **The current two-capability surface has a lexical/structural URL affordance collision: the destination URL from the user task can fit the shallow field vocabulary of both the eye and the hand, even though only the hand owns navigation.**

This does not mean the model lacks the concept of navigation. Every failed call recovered on the next Browser call by using the hand correctly. The failure is at the provider tool-selection/argument affordance boundary.

## 6. Candidate A' boundary — disambiguate URL role, do not teach a routing protocol

If A is implemented later, the first correction should be narrower than another rename or a routing decision tree.

Recommended deterministic target:

1. `browser_operate` remains the only provider capability with a destination field named `url` and `do=navigate`.
2. Perceive `page_url` wait uses an observation-specific field such as `expected_url` rather than the same destination-looking `url` key.
3. Perceive continues to reject `action=navigate` and `snapshot + URL-field` combinations fail-closed.
4. Internal compatibility may translate the provider facade mechanically, but the provider-visible Perceive surface must not expose the old ambiguous field.
5. No user-text router, keyword rule, thought template, decision tree or automatic correction is added.
6. Static tool ordering may be evaluated independently only after this affordance collision is removed; do not combine both changes in one causal commit.

The exact field name is a future RED decision, not finalized by this audit. The invariant is **destination URL and observed/waited URL must not look like the same provider argument role**.

---

# Part B — post-success verification and evidence amplification

## 7. MF532 Row2: the action succeeded long before the timeout

MF532 `fill_submit r1` is not a task-action failure.

The frozen event stream shows:

1. `browser_operate(do=navigate)`
2. snapshot
3. `browser_operate(do=set_text, Project code=AB-7319)`
4. `browser_operate(do=click, Save code)`
5. snapshot
6. `read_evidence`
7. hydrate one object
8. hydrate another object
9. hydrate two more objects
10. snapshot with `projection_limit=500`
11. `read_evidence`
12. a long decode with no tool draft, then worker timeout

The external fixture oracle recorded exactly one `save_code` with value `AB-7319`.

After the terminal click alone, the model spent:

- **7 additional tool-bearing rounds**;
- **8 additional tool calls**: snapshot×2, hydrate×4, read_evidence×2;
- about **77,131 input tokens** and **1,511 output tokens** before round 12;
- about **48.3s provider execution time** in rounds 5–11.

Round 12 then produced no tool call and no visible answer. Partial checkpoints span about **173s**, with reasoning state growing continuously until the 240s worker bound was reached.

The correct interpretation is therefore two-stage:

1. **observable verification/evidence amplification** after the real mutation already succeeded;
2. **a later decode/reasoning loop** after the available evidence still did not make the success fact mechanically legible enough.

Increasing max iterations or worker timeout would only give this loop more room. It is not the primary correction.

## 8. The amplification is systematic, not a single timeout anomaly

Post-terminal tool activity from the frozen traces:

| Identity / row | Post-terminal pattern | Approx post-terminal input tokens |
|---|---|---:|
| MF531 click r1 | wait + snapshot + read evidence | 34.8k |
| MF531 fill r1 | wait + snapshot + read evidence | 44.5k |
| MF531 delayed r1 | no extra tool call | 7.0k |
| MF531 delayed r2 | snapshot + read evidence×2 | 75.2k |
| MF531 fill r2 | hydrate + read evidence×4 + snapshot | 59.6k |
| MF531 click r2 | snapshot + read evidence | 38.1k |
| MF532 click r1 | wait + snapshot + read evidence×3 | 61.6k |
| MF532 fill r1 | snapshot×2 + hydrate×4 + read evidence×2, then decode loop | 77.1k before final loop |
| MF532 delayed r1 | wait | 14.4k |
| MF532 delayed r2 | no extra tool call | 7.1k |
| MF532 fill r2 | wait + snapshot×2 + hydrate + read evidence×2 | 65.7k |
| MF532 click r2 | wait×2 + snapshot×2 + hydrate + read evidence×2 | 76.8k |

The exact token sums are diagnostic, not a correctness score. The pattern is enough to establish that post-success confirmation is a recurring cost center, especially for click/fill tasks.

## 9. Compact operation delta is truthful but insufficiently self-describing

The successful `Save code` click returned a compact receipt with:

```text
status=completed
match_count=1
automatic_retry=false
delta.comparable=true
delta.complete=false
delta.counts.changed=0
delta.counts.created=1
delta.counts.removed=1
delta.reasons=[identity_unstable_objects]
```

The runtime correctly refuses to interpret this as task completion.

The persisted exact diff shows the created/removed stable subset, but the compact receipt exposes only counts + exact `diff_ref`. The useful human-level change (`Not submitted` → `Submitted`) is not attached to the stable `Submission status` semantic object.

This forces escalation from receipt → snapshot/hydrate/evidence even though the task-relevant change physically happened.

## 10. Exact representation gap: direct DOM text is dropped, AX text is detached

The fixture contains:

```html
<div id="receipt" aria-label="Submission status">Not submitted</div>
```

After a successful server receipt, JavaScript sets the div's text to `Submitted`.

The frozen post-click Browser snapshot contains:

- a complete/stable DOM+AX object named `Submission status`, but **without `attributes.text`**;
- separate AX-only objects named `Submitted` (`StaticText` / `InlineTextBox`), with no structural relation back to the `Submission status` object.

Current capture behavior explains this exactly:

1. DOMSnapshot text nodes are skipped because node names beginning with `#` are not emitted as DOM semantic nodes.
2. Element `attributes.text` is populated only from the element node's own `nodeValue`, which is normally empty for an element whose text lives in a child text node.
3. Accessibility nodes are captured with role/name/value/backend identity, but their `parentId` lineage is not carried into the Browser perception adapter.
4. `_attach_structural_relations()` builds parent/child relations only from DOM element nodes.
5. AX-only text fragments therefore have `relations=[]`.

A zero-model synthetic capture using the current code reproduced the same structure: a `div` with direct `#text` child `Submitted` becomes a stable `Submission status` object with no text plus a detached AX `Submitted` object.

The repository already demonstrates that `Accessibility.getFullAXTree` exposes `parentId`: the legacy read-only AX helper uses it to reconstruct an AX tree. The current Perception backend simply does not preserve it.

## 11. Candidate B1 boundary — preserve direct DOM text on its exact stable parent

The narrowest correction is smaller than AX fusion and does not need a new schema field.

`smc.semantic_object.v0.1` already allows `attributes.text`, and the semantic diff implementation already detects `attributes.text` changes on a stable object.

Recommended deterministic target:

1. During DOMSnapshot capture, preserve non-empty **direct child text-node** values on their exact DOM parent as `attributes.text`.
2. Use DOM structural `parentIndex` only; no selector, name match, task text, intended action or relevance score participates.
3. Preserve DOM order deterministically if multiple direct text children exist.
4. Do not remove or merge AX text fragments in B1; canonical source evidence remains available.
5. Do not infer `task_completion` from the text.
6. Do not change target matching, retry, grounding or mutation authority.
7. Existing outer evidence projection remains responsible for provider-visible size; do not solve this by globally raising the evidence budget.

For the frozen Row2 snapshot, an audit-only projection simulation that adds `text="Submitted"` to the already-stable `Submission status` parent places that object at projection index **0**, with `Submitted` at serialized character offset **88** — well inside the existing 3k/5k visible head budget. No global evidence-budget expansion is required to make the fact immediately legible.

This correction also improves the exact diff shape: the same stable parent can mechanically report a changed `attributes.text` field instead of requiring the model to infer a relationship between detached AX fragments.

## 12. Why AX lineage is deferred to B2

Capturing AX `parentId` into structural relations is legitimate and task-invariant. It may still be useful after B1, especially where text has no direct DOM parent representation.

But it is a broader first correction because:

- it extends the fusion/relationship substrate for every AX-only node;
- a parent relation points to an object ID but does not itself surface the child's textual value on the complete parent;
- the frozen timeout fixture can be repaired more narrowly by preserving a fact the DOM snapshot already contains.

Therefore the first deterministic correction should not combine direct DOM text preservation with AX lineage. Keep B1 and any later B2 independently attributable.

---

# 13. Recommended work order

The two residuals are independent enough to remain separate.

### First: B1 — direct DOM text preservation

Reason:

- it has an exact frozen hard-failure chain ending in the Row2 timeout;
- current production behavior can be reproduced without a model;
- the target field (`attributes.text`) already exists in the closed schema;
- semantic diff already knows how to report changes to that field;
- an audit-only replay shows the missing `Submitted` fact would land at the very front of the existing quality projection;
- it does not require changing model routing, task authority or evidence budgets.

### Second: A' — URL-role affordance disambiguation

Reason:

- A name-only rename is demonstrably insufficient;
- the URL cross-binding is mechanically visible in all remaining routing repairs;
- but the exact causal contribution of tool order is not established, so provider reordering should not be bundled into the first A' change.

Proposed future sequence after human approval:

```text
B1 deterministic RED
→ B1 implementation
→ B1 focused + Browser deterministic qualification
→ A' deterministic RED
→ A' provider-facade implementation
→ full non-real qualification
→ fresh measured protocol / zero-model preflight
→ live treatment only after a new human checkpoint
```

This ordering is about causal confidence, not importance ranking. The final Gate still requires both verification integrity and routing repair to reach zero failures.

## 14. Explicitly rejected shortcuts

Do not use the following as the next correction:

- increase `max_iterations` or the 240s worker timeout;
- globally enlarge Evidence projection;
- hide verification evidence or declare receipt `ok` as task completion;
- auto-stop after a successful mutation;
- fuzzy-match or auto-substitute a target;
- retry/replay a mutation automatically;
- add navigation to Perceive;
- add a model-facing routing decision tree / Observe→Act thought protocol;
- combine provider ordering, URL-role rename and DOM-text preservation into one commit;
- start MF-6.

## 15. Phase boundary

This read-only audit is complete. The next action requires a human checkpoint before any RED or production edit.
