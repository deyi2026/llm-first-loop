# SMC Browser MF-5.3.2 — Read-Only Interface Audit — 2026-09-16

Status: **READ-ONLY AUDIT COMPLETE / NO PRODUCTION CHANGE / MF-6 DEFERRED**

Formal evidence anchor: `914f98d7f6f0181bab60f68e9e5264908b7ed373`

MF-5.3.1 implementation anchor: `1cb9ad2bddd8b44ca31dd38ff1b30c9dd42c01e0`

Primary measured result: `docs/SMC-BROWSER-COGNITION-PRESERVING-MF5.3.1-v0.1-RESULT-20260916.md`

## 1. Audit question

MF-5.3.1 established two facts at the same time:

1. the root-direct Perceive correction solved the exact wire defect it was designed to solve;
2. the treatment still failed the frozen hard Gate.

The measured result was 5/6 task-correct with valid infrastructure and healthy hard safety boundaries. The old MF-5.3 nested `condition` / hydrate+`projection_limit` repair classes disappeared completely, but three first Browser calls still went to the wrong capability and one fill task failed after the model selected an ambiguous AX text-fragment identity instead of the available complete button identity.

MF-5.3.2 therefore asks two independent interface questions without changing production:

1. **Capability routing salience:** why does a model that clearly understands “open/navigate the page” route that intent to Perceive on 3/6 first Browser calls even though Operate owns `navigate`?
2. **Actionable-object perception salience:** why can a partial AX text fragment named `Save code` become more cognitively visible than the complete enabled DOM+AX button with the same name?

A third issue — evidence paging / iteration amplification after ambiguity — is audited only as a consequence. Increasing the iteration budget is not considered a root-cause correction.

No new model run, production edit, provider-schema edit, Gate edit, or replay belongs to this phase.

---

## 2. Evidence base and causal boundaries

### 2.1 Frozen measured facts

MF-5.3.1 v0.1:

- external task oracle: **5/6**;
- click: 2/2;
- delayed-wait: 2/2;
- fill-submit: 1/2;
- first Browser call contract-valid: **3/6**;
- Perceive failures/errors: **3/0**;
- Operate failures/errors: **0/0**;
- observable protocol repair: **3**;
- Grounding Probe Amplification: **1**;
- duplicate successful mutation: 0;
- `get_tool_schema`: 0;
- hidden atomic Browser calls: 0;
- automatic mutation retry: 0;
- task-completion authority violation: 0;
- undeclared-boundary continuation: 0;
- fallback: 0.

The result was frozen at `914f98d7`; none of these rows are replayed in this audit.

### 2.2 The intended MF-5.3.1 fix did work

Compared with MF-5.3 v0.1:

- protocol repair: 8 -> 3 (-62.5%);
- Perceive failures: 8 -> 3 (-62.5%);
- rounds: 68 -> 57 (-16.2%);
- Perceive calls: 29 -> 21 (-27.6%);
- `read_evidence`: 23 -> 18 (-21.7%);
- Browser argument chars: 3,170 -> 2,134 (-32.7%);
- Browser result chars: 94,903 -> 74,674 (-21.3%);
- input tokens: 632,206 -> 482,204 (-23.7%);
- output tokens: 11,741 -> 7,126 (-39.3%).

The exact old failure classes occurred zero times:

- nested `condition` serialized as a JSON string: 0;
- hydrate carrying snapshot-only `projection_limit`: 0.

Therefore MF-5.3.2 must not undo root-direct Perceive or reintroduce permissive cross-action bags.

### 2.3 Hard causal boundary for this audit

The remaining three Perceive failures are not evidence that Perceive should gain mutation authority.

They are evidence that the **model-facing distinction between two legitimate peer capabilities is not yet sufficiently natural/stable**.

Likewise, the Row5 ambiguous target is not evidence that exact grounding should be replaced by fuzzy/best-match target choice. The runtime did the right thing by halting.

---

## 3. Audit A — capability-routing salience

## 3.1 Actual provider-visible Browser surface

Factory registers Browser capabilities in this order:

1. `browser_perceive`;
2. `browser_semantic_operation` when mutation is enabled.

`ToolRegistry.schemas()` preserves registry insertion order.

The formal measured lazy surface therefore presents Perceive before Operate.

Current compact contracts are already mechanically truthful:

### `browser_perceive`

- read-only snapshot/hydrate/diff/wait;
- page wait mechanically binds the current host-bound page;
- object wait requires exact `object_ref`;
- explicitly says **no navigation / no mutation**;
- no fuzzy/latest/rebind/retry/completion authority.

### `browser_semantic_operation`

- one already-decided mutation;
- `do=navigate|click|set_text|append_text|select|scroll`;
- explicitly says wait belongs to `browser_perceive`;
- exact semantic identity for object mutation;
- no fuzzy/rebind/retry/completion authority.

So this is not a simple “description forgot to mention navigate” bug.

## 3.2 First-call evidence: task intent is correct, routing is unstable

All six rows begin with essentially the same natural reasoning:

> open / navigate to the page first

But the first Browser call splits 3/3:

| Row | Natural first intent | First Browser tool | Result |
|---:|---|---|---|
| 1 click-r1 | navigate/open page | `browser_semantic_operation(do=navigate)` | valid |
| 2 fill-r1 | open page | `browser_perceive(action=navigate,url=...)` | invalid |
| 3 wait-r1 | open page | `browser_perceive(action=snapshot,url=...)` | invalid |
| 4 wait-r2 | open page | `browser_semantic_operation(do=navigate)` | valid |
| 5 fill-r2 | open page | `browser_perceive(action=navigate,url=...)` | invalid |
| 6 click-r2 | navigate/open page | `browser_semantic_operation(do=navigate)` | valid |

After each invalid Perceive call, the model recovered to the correct Operate navigate without `get_tool_schema`.

This is strong evidence that:

- the semantic intent itself is understood;
- the model can infer the correct action contract after explicit failure;
- the unstable part is **capability selection at first call**.

## 3.3 Tool order is a real fact, but a weak primary fix

Perceive is registered first and therefore appears first in the provider tool array.

This may contribute to selection bias, but the six-row matrix cannot establish that order is causal. More importantly, order is a poor semantic contract:

- provider/tool-selection implementations may change weighting;
- future support tools may alter positions;
- correct routing should not depend on “the right tool happens to be second”.

**Ruling:** do not make tool reordering the primary correction.

Order can be held constant or treated as a diagnostic in a future qualification, but capability identity should carry the semantic distinction itself.

## 3.4 The current names are cognitively asymmetric

The intended architecture is conceptually symmetric:

`Perceive = eye`

`Operate = hand`

The actual provider names are asymmetric:

`browser_perceive`

`browser_semantic_operation`

`perceive` is a common action concept. `semantic_operation` is longer, more abstract, and reads like an implementation/framework term rather than the natural peer verb of `perceive`.

The measured failures are consistent with — but do not by themselves prove — this naming asymmetry being material.

The strongest model-facing candidate is therefore:

`browser_perceive`

`browser_operate`

This is a **capability label**, not a thought protocol.

## 3.5 Why description-only expansion is not the preferred first correction

The current compact descriptions already contain the decisive facts:

- Perceive: no navigation/mutation;
- Semantic Operation: `navigate` is a supported mutation.

Adding a longer routing decision tree would increase stable-prefix protocol text and risks recreating protocol-induced reasoning.

A better cognition-preserving surface should need **less prose because the capability names carry more meaning**.

Recommended compact semantics are role-like, not procedural:

- Perceive: read-only browser observation/wait; never opens/navigates/changes the page.
- Operate: browser actions, including open/navigate/click/type/select/scroll; mutation only, no wait.

Do not add “first decide X, then choose Y” instructions.

## 3.6 Do not expose both old and new “hand” names

Exposing both:

- `browser_semantic_operation`
- `browser_operate`

would create three Browser cognitive concepts instead of two and reintroduce a routing problem.

If a provider-visible rename is implemented, backward compatibility should live **behind** the model surface:

- internal class/storage/receipt schemas may retain historical names;
- a hidden execution alias or adapter may preserve compatibility if needed;
- only one actuation capability name should be provider-visible.

The exact compatibility mechanism is an implementation question for a later phase; the read-only architecture requirement is one visible hand, not two.

## 3.7 Progressive Method and stale guidance audit

`methods/method-semantic-operation/METHOD.md` still teaches the older flow:

- mandatory Observe -> Ground -> Execute -> Receipt -> Re-observe/Verify;
- exact `GroundingRef` selection;
- direct use of low-level `browser_semantic_execute`.

This is inconsistent with the current two-capability provider normal form.

However, the MF-5.3.1 measured event logs contain **zero** occurrences of that Method text / `browser_semantic_execute` guidance. Therefore it is a real consistency debt, but not an evidenced cause of the three first-call failures.

Before that Method is relied upon again it should be updated to the cognition-preserving two-capability architecture. It should remain progressive disclosure, not stable-prefix routing policy.

## 3.8 Stale compact parameter entry is inert in the measured surface

`_COMPACT_PARAMETER_DESCRIPTIONS` still contains a historical `browser_semantic_operation.steps` entry.

The current operation tool declares explicit `lazy_parameters = parameters`; `ToolRegistry._lazy_parameters()` returns that explicit schema **before** applying the compact-parameter table.

The formal measured surface also reports `operation_has_steps=false`.

Therefore the stale entry did not enter this experiment. It should eventually be removed as maintenance debt, but it is not a causal explanation for MF-5.3.1.

### Audit A ruling

The two-capability architecture remains correct.

The preferred next routing correction is **provider-visible peer capability identity**, not more routing prose and not order dependence:

- keep `browser_perceive` as the read-only eye;
- expose one natural peer hand, preferably `browser_operate`;
- keep navigation exclusively on the hand;
- do not expose both old and new hand names;
- remove stale Method/stable-prefix asymmetries as consistency cleanup in the same qualified tranche only if deterministic evidence covers them.

A fresh live qualification is still required; this audit does not claim a rename will solve routing by itself.

---

## 4. Audit B — actionable-object perception projection

## 4.1 Capture and canonicalization pipeline

The Browser perception path is mechanically layered:

1. read-only CDP capture obtains DOM + AX facts;
2. DOM nodes receive backend physical identity;
3. AX nodes carry `backendDOMNodeId` when Chrome supplies it;
4. AX nodes sharing exact backend physical identity with a DOM node may be fused;
5. unmatched AX nodes become independent SemanticObjects;
6. exact source/object grounding is persisted;
7. model-facing snapshot returns a bounded `objects` projection plus exact `objects_ref`.

No task text participates in canonical identity.

## 4.2 Why `Save code` became three SemanticObjects

The failed Row5 snapshot contains three objects whose semantic name is exactly `Save code`:

### Complete actionable parent

- kind=`button`;
- coverage status=`complete`;
- sources=`dom + ax`;
- stable DOM physical identity;
- enabled=true.

### AX text fragment 1

- role=`StaticText`;
- normalized kind=`generic`;
- AX-only / partial coverage.

### AX text fragment 2

- role=`InlineTextBox`;
- normalized kind=`generic`;
- AX-only / partial coverage;
- snapshot-local in one observed instance.

This is not name-based duplication by the canonicalizer. It is the truthful consequence of available source identity:

- the AX button has a backend DOM node ID and is fused with the DOM button;
- child StaticText / InlineTextBox AX nodes may lack a backend DOM node ID;
- they therefore cannot be proven to be the same physical object as the button.

## 4.3 AX lineage that could disambiguate parent/child is currently dropped

CDP AX nodes can carry structural lineage identifiers, but the current Browser capture projection retains only:

- AX node ID;
- optional backend DOM node ID;
- frame token;
- role/name/value/state.

The current transform does not preserve AX parent/child lineage into the normalized sensor node.

Later, `_attach_structural_relations()` attaches parent/child relations **only from DOM nodes**.

Therefore AX-only InlineTextBox / StaticText fragments cannot mechanically point back to their actionable AX parent in the current SemanticObject projection unless physical DOM identity already proves the link.

This is a real information-loss boundary.

## 4.4 The immediate salience problem is projection order, not canonical truth

After canonicalization, the adapter currently performs:

`objects_sorted = sorted(build.semantic_objects, key=lambda item: item["id"])`

Semantic IDs are opaque hashes.

So the model-facing object order is effectively **identity-hash order**, not:

- source confidence;
- coverage completeness;
- identity stability;
- UI/actionability;
- DOM/AX parenthood;
- document order.

Then the result returns:

`objects_sorted[:projection_limit]`.

This is mechanically deterministic but cognitively arbitrary.

## 4.5 Row5 exact projection evidence

The first failure-relevant Row5 snapshot has:

- 23 projected objects;
- 4 snapshot-local AX objects;
- 5 complete-coverage objects;
- 2 objects in the obvious interactive-kind set (`input`, `button`).

Under current opaque-ID order:

- `Project code` input: index 1;
- a `Save code` AX InlineTextBox generic: index 0;
- complete `Save code` button: index 14.

The exact serialized snapshot result is about 18K chars.

The complete button's model-facing object body begins around the 10K region.

## 4.6 Generic Evidence projection makes the arbitrary order user-visible

Browser tool results are then passed through the generic Evidence projection layer.

For ordinary tools other than exact `read_file`, the model-visible Evidence budget is 5,000 chars.

When an observation exceeds that budget, the generic projector keeps approximately:

- 60% head;
- factual omission marker;
- 40% tail.

The full exact bytes remain behind an EvidenceRef.

For the first Row5 snapshot:

- exact content length: 18,036 chars;
- approximate visible head: 2,962 chars;
- approximate visible tail begins around 16,061;
- AX InlineTextBox `Save code`: appears at about char 75/91 -> visible immediately;
- complete `kind=button, name=Save code`: around 10.1K -> hidden in the omitted middle.

For the later Row5 snapshot:

- exact content length: 19,288 chars;
- complete `Save code` button: around 10.8K -> omitted;
- all three `Save code` name occurrences fall outside the visible head/tail.

This directly explains why the model then used `read_evidence`: it was recovering exact facts hidden by a generic projection, not merely “thinking too long”.

## 4.7 Two projection layers currently have different completeness meanings

The Browser snapshot may truthfully say its own `objects_projection.complete=true` because all 23 objects were included in the tool's raw result.

The outer Evidence layer then says `evidence_projection_complete=false` because that raw result was reduced to a 5K excerpt before reaching the model.

Both statements are mechanically correct at their own layers, but the composition is suboptimal for a structured perception tool.

The model may receive a “complete Browser projection” whose decisive middle objects are nevertheless absent from the provider-visible message.

This is another reason to treat Browser model projection as a first-class interface rather than relying indefinitely on a generic text head/tail excerpt.

---

## 5. Read-only counterfactual projection experiment

No code was changed. Persisted MF-5.3.1 snapshots were re-ordered offline only.

## 5.1 A task-specific actionability sort is not necessary

One obvious counterfactual is to put interactive kinds first.

That works on Row5:

- `Project code` input -> index 0;
- `Save code` button -> index 1;
- button ref appears around 1.1K and becomes visible in the existing 5K head.

But hard-coding “actionability first” introduces an unnecessary semantic preference into the sensor projection.

A more conservative mechanical criterion is enough.

## 5.2 Evidence-quality ordering is sufficient on the entire measured corpus

Counterfactual order:

1. complete coverage before partial coverage;
2. non-snapshot-local identity before snapshot-local AX identity;
3. existing opaque ID order as deterministic tiebreaker.

This uses evidence quality and identity stability only. It does not use:

- task text;
- object name;
- intended verb;
- relevance prediction;
- success prediction.

Across **63 persisted snapshots** from the six formal rows:

- actionable object instances: 73;
- current opaque-ID order median actionable index: **11**;
- current mean: **10.62**;
- current max: **24**;
- current top-3: 17/73;
- current top-5: 26/73.

With complete/stable evidence-quality ordering:

- median actionable index: **1**;
- mean: **1.52**;
- max: **4**;
- top-3/top-5: **73/73 are top-5**.

The same holds for named task-relevant actionable instances in this frozen matrix.

For the exact failed Row5 snapshot:

- `Save code` button: index 14 -> **index 3**;
- serialized button ref: about 10.0K -> **about 2.57K**;
- it becomes visible inside the existing 5K Evidence head.

This is strong evidence that an evidence-quality projection order is a viable narrow correction.

It is not proof that the same ordering is globally optimal; deterministic RED and broader regression must define the contract before implementation.

## 5.3 Why this does not give the program target-selection authority

Projection order answers:

> Which already-observed facts should be shown earlier under a bounded representation?

It does not answer:

> Which object should the model click for this task?

Every object remains exact evidence with the same semantic identity and grounding ref.

The model still decides:

- which object is relevant;
- which action is intended;
- whether ambiguity requires more evidence;
- whether the task is complete.

The runtime still rejects non-unique exact identities.

---

## 6. Where to apply ordering without corrupting canonical evidence

The canonical persisted object set should remain authoritative and task-invariant.

Recommended separation:

### Canonical layer

Keep:

- exact SemanticObject facts;
- exact source grounding;
- full object set;
- immutable refs;
- content/diff semantics;
- no task-based reorder/dedup.

### Model projection layer

May mechanically choose a deterministic display order using evidence-quality facts already present in the canonical objects.

The narrowest contract is:

`complete coverage -> stable/non-local identity -> canonical id tiebreaker`

This ordering can be used consistently by the returned projection while preserving `objects_ref` to the canonical complete list.

Important implementation caveat: `browser_semantic_operation` also captures a projection for exact-identity grounding. A future change must ensure model-visible projected identities and actuation grounding remain aligned under projection caps. Do not create a state where the model can see an object that the actuation projection cannot ground.

A deterministic RED should lock this alignment explicitly.

---

## 7. AX lineage: useful second-stage evidence, not the first patch

Preserving AX parent/child lineage could allow the perception layer to state mechanically:

- this InlineTextBox is a child/descendant of this button;
- this StaticText belongs under this actionable parent.

That would help the model understand why same-name fragments exist.

However, lineage should not immediately be used to silently delete or merge child objects.

Safe future options include:

- exact `relations` from AX lineage;
- parent reference annotations when the lineage is proven;
- projection de-prioritization of child text fragments when a complete parent is present.

Unsafe shortcuts include:

- merge by equal name;
- drop every InlineTextBox/StaticText;
- assume a same-name button is always the intended target.

Because evidence-quality ordering already moves the Row5 button into the visible head without requiring new capture semantics, AX lineage should be a **second-stage** investigation after the narrower projection-order correction is qualified.

---

## 8. Generic Evidence projection: preserve it for now, but do not confuse it with an ideal Browser UI

Increasing the generic Evidence budget would reduce truncation but increase stable token cost for every large tool result. It also leaves opaque object ordering untouched.

Therefore do not solve MF-5.3.2 by changing the global 5K budget.

A future Browser-specific compact perception projection may be valuable:

`durable full semantic objects -> compact high-quality object cards -> exact hydrate/full_ref`

Such cards could carry only the facts needed for normal cognition, for example:

- kind;
- name/role;
- relevant state;
- coverage/status;
- exact grounding ref.

This mirrors the already successful compact-receipt principle.

But that is a larger surface change than deterministic reordering. It should be considered only if a qualified ordering/routing correction still leaves substantial `read_evidence` amplification.

---

## 9. Iteration budget is not the primary remedy

Row5 exhausted 12 rounds after:

1. first-call routing repair;
2. snapshot/evidence recovery;
3. successful input mutation;
4. ambiguous generic click;
5. exact hydrate;
6. fresh snapshot;
7. repeated evidence paging.

Raising `max_iterations` would likely give the model more time to eventually recover, but it would preserve the same interface taxes.

The correct order is:

1. make capability ownership natural;
2. make high-quality perception facts visible under the existing bound;
3. then measure whether the existing iteration limit remains a real task-capacity bottleneck.

---

## 10. Authority boundary

MF-5.3.2 does not change LLM-First authority.

### Program may

- label one provider capability as read-only perception and one as mutation/operation;
- mechanically expose only one visible name for each capability;
- preserve compatibility aliases internally without exposing extra model concepts;
- prioritize model-facing evidence by task-independent evidence quality/completeness/identity stability;
- preserve exact AX structural lineage when the browser reports it;
- persist the full canonical object set and exact refs;
- expose omitted evidence through durable refs;
- keep exact non-unique grounding fail-closed.

### Program may not

- add navigation to the read-only Perceive capability;
- infer that “Save code” means the user wants the button rather than the text;
- choose a target because it is actionable;
- fuzzy/best-match or silently coerce `generic` to `button`;
- delete conflicting evidence merely to make a call succeed;
- auto-retry/replay a mutation;
- decide task completion;
- raise the iteration budget to conceal routing/perception defects.

### Model remains responsible for

- task meaning;
- which capability/action it wants;
- which visible object is semantically relevant;
- how to resolve genuine ambiguity using evidence;
- whether the observed state satisfies the user's request.

---

## 11. Recommended deterministic RED split

Do not implement routing and projection in one unreviewable patch.

Recommended next identity after human approval:

## MF-5.3.2A — capability identity RED

Freeze model-facing requirements:

- exactly two Browser capabilities remain visible;
- peer semantic names are natural and symmetric;
- preferred target pair: `browser_perceive` + `browser_operate`;
- navigation exists only on Operate;
- wait exists only on Perceive;
- old actuation name is not simultaneously provider-visible;
- compact descriptions state capability boundaries without a routing decision tree;
- Perceive stable prefix no longer depends on a stale Method ref;
- internal receipt/storage schema identity may remain historical;
- no change to mutation semantics, grounding, retry, completion authority.

RED should avoid over-constraining the internal alias/compatibility mechanism.

A live treatment is required to establish whether the provider-visible name correction actually improves first-call routing.

## MF-5.3.2B — evidence-quality projection RED

Freeze model-facing projection requirements:

- canonical persisted `objects` and exact refs remain unchanged;
- full `objects_ref` hydration remains exact;
- display order is deterministic and task-independent;
- complete evidence precedes partial evidence;
- snapshot-local AX identity does not outrank otherwise equivalent stable evidence;
- canonical opaque ID remains a deterministic tiebreaker;
- no name/task/verb relevance scoring;
- no fuzzy merge or target substitution;
- model-visible projection and Operate grounding remain compatible under projection caps;
- Row5-style complete `button` is visible before same-name partial AX text fragments under the frozen fixture.

Cross-snapshot regression should include the full 63-snapshot frozen evidence corpus or deterministic fixtures representing the same identity/coverage classes.

## 11.3 Sequence recommendation

Recommended implementation/qualification order:

1. MF-5.3.2A deterministic RED;
2. narrow provider-visible capability identity correction;
3. deterministic qualification;
4. MF-5.3.2B deterministic RED;
5. narrow evidence-quality projection-order correction;
6. all Browser/Factory/full non-real gates;
7. freeze a new measured identity with the same six-row tasks/fixture/prompt/Gate;
8. zero-model preflight;
9. fresh live treatment;
10. only after treatment hard-PASS, independent repeat / MF-6 consideration.

This order makes each correction attributable.

---

## 12. Items explicitly deferred

Do not include these in the first MF-5.3.2 production tranche:

- global Evidence budget increase;
- Browser snapshot compact-card redesign;
- AX parent/child capture and relation semantics;
- removal/merging of AX text fragments;
- changed iteration limit;
- fuzzy/best-match target repair;
- automatic target substitution;
- automatic mutation retry;
- task-completion heuristics;
- MF-6.

They remain follow-up candidates only if evidence after the narrow corrections justifies them.

---

## 13. Final audit ruling

MF-5.3.1 did not falsify the two-capability architecture. It exposed the next two interface taxes:

1. **the eye and hand are mechanically separate but not yet named/presented as equally natural peer capabilities;**
2. **the sensor stores correct exact objects, but an opaque-ID projection followed by generic text truncation can make partial AX fragments more visible than complete stable objects.**

The first correction should improve **capability identity**, not teach a routing protocol.

The second should improve **evidence-quality projection order**, not choose a task target.

The strongest narrow perception result from the frozen corpus is especially important:

> Complete/stable evidence-quality ordering alone moved all 73 actionable instances across 63 measured snapshots into the top five projected positions, while using no task text, object name, intended verb, relevance model, or task-success heuristic.

That is the preferred LLM-First direction: improve the eye's signal quality while keeping semantic choice with the model.

MF-6 remains deferred.


---

## 14. Mechanical failure decomposition and formal evidence freeze

This section freezes the exact failure mechanics requested before any new correction identity.

### 14.1 The three Perceive failures are capability-routing failures

| Row | First Browser call | Exact mechanical rejection | Classification |
|---:|---|---|---|
| 2 fill-r1 | `browser_perceive(action=navigate, url=...)` | `[browser_perceive] action must be snapshot/hydrate/diff/wait` | mutation/navigation intent routed to the read-only eye |
| 3 wait-r1 | `browser_perceive(action=snapshot, url=...)` | `[browser_perceive:snapshot] fields_mismatch: snapshot does not accept ['url']` | navigation URL attached to an observation action |
| 5 fill-r2 | `browser_perceive(action=navigate, url=...)` | `[browser_perceive] action must be snapshot/hydrate/diff/wait` | mutation/navigation intent routed to the read-only eye |

All three occur on the first Browser call. All three recover without `get_tool_schema`. None is the old MF-5.3 nested-`condition` or hydrate+`projection_limit` defect.

### 14.2 Row5 Grounding Probe Amplification is a different mechanism

The failed Row5 mutation was:

`browser_semantic_operation(do=click, target={kind:generic, name:"Save code"})`

The full receipt correctly halted with:

- `exact_match_count=2`;
- `halt_reason=exact_identity_match_count:2`;
- `automatic_retry_performed=false`;
- `task_completion=not_evaluated`.

The runtime therefore preserved the authority boundary. The defect is upstream visibility/selection pressure, not fail-closed grounding.

The failure-relevant persisted snapshot `bsnap-1-f132fed5fb8ce290` contains 23 objects. Exact positions under the current opaque-ID projection are:

- index 0: AX-only `InlineTextBox`, `kind=generic`, `name=Save code`, partial coverage;
- index 1: complete DOM+AX `input`, `name=Project code`;
- index 11: AX-only `StaticText`, `kind=generic`, `name=Save code`, partial coverage;
- index 14: complete DOM+AX `button`, `name=Save code`, `enabled=true`.

In the serialized object projection, the first `Save code` fragment appears essentially at the beginning, while the `kind=button` object begins around char 10.8K. The outer generic Evidence layer then exposes only a bounded head/tail excerpt around 5K chars, so the actionable button falls in the omitted middle while a generic text fragment is immediately visible.

### 14.3 Adjudication: not one narrow interface gap

The evidence does **not** support collapsing the remaining failure surface into one correction identity.

There are two independent mechanical taxes:

1. **capability-routing salience** — correct navigation intent is sometimes dispatched to the wrong peer capability before any page evidence exists;
2. **perception projection salience** — after valid perception, exact actionable controls can be less visible than partial AX text fragments because opaque-ID ordering composes poorly with the outer bounded Evidence excerpt.

Therefore this audit does **not** authorize one combined production patch. The next deterministic work, if approved, should remain split into MF-5.3.2A and MF-5.3.2B so each correction is attributable.

### 14.4 Frozen artifact manifest

The machine-readable companion is:

`docs/SMC-BROWSER-MF5.3.2-READ-ONLY-INTERFACE-AUDIT-20260916.json`

It freezes:

- the committed MF-5.3.1 formal result artifacts from `914f98d7` by SHA-256 and byte length;
- the exact Rows 2/3/5 raw event logs and worker outputs used for routing-failure attribution;
- the Row5 failure-relevant persisted snapshot and halted full operation receipt;
- the measured failure taxonomy and the 63-snapshot counterfactual metrics;
- `same_narrow_interface_gap=false` as the audit adjudication.

No measured row, Gate, production source, provider contract, test, or runtime state is modified by this freeze.
