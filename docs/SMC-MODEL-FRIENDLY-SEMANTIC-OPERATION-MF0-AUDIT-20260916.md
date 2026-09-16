# SMC Model-Friendly Semantic Operation — MF-0 Interface Tax Audit — 2026-09-16

Status: **READ-ONLY AUDIT COMPLETE / NO PRODUCTION CODE CHANGED**

Code baseline: `lfl/main@2c4b9b087f5d2fad2cf2c5c026194038c7613c5c`

Design target: `docs/SMC-MODEL-FRIENDLY-SEMANTIC-OPERATION-DESIGN-v0.1-20260916.md`

## 0. Ruling

The current bounded semantic operation is mechanically sound enough to be the backend basis for the next experiment, but its **model-facing wire and result path still charge protocol tax**.

The next implementation should therefore be an interface compiler/projection change around the existing qualified mechanics, not a rewrite of Browser actuation, grounding, Predicate semantics or ActionReceipt authority.

Most important finding:

> Current inefficiency is not dominated by JSON bytes alone. It is dominated by interaction amplification when a first call is invalid and the model then spends rounds on schema lookup and exact evidence hydration before returning to the same semantic intent.

This is visible in FC2-B: 31 semantic-operation calls were accompanied by 7 schema lookups and 27 evidence reads across only six tasks.

---

## 1. Authoritative current mechanics

`BrowserSemanticOperationTool` currently:

- accepts 1..8 ordered clauses;
- exact-matches object identity using `kind/role/name`;
- halts when exact match count is not exactly 1;
- snapshots internally before grounding each clause;
- delegates mutation to `browser_semantic_execute`;
- delegates wait to typed Predicate polling;
- embeds the full returned `action_receipt` into each mutation clause result;
- never fuzzy-matches, auto-targets, substitutes latest, rebinds, retries or judges task completion.

The mutation backend already performs:

```text
pre-capture -> version assessment -> single dispatch -> post-capture -> semantic diff -> ActionReceipt
```

Therefore the older model-facing instruction “after ActionReceipt, call snapshot again to re-observe/verify” is not universally necessary. It is justified only when the model needs semantic context not represented by the fresh post-action delta/evidence.

---

## 2. Input field classification

Classification:

- **A — model-semantic required**: removing it would transfer a semantic decision to the program;
- **B — mechanically derivable / structural tax**: program can derive or encode it without choosing task strategy;
- **C — evidence-only**: durable authority should retain it, but normal model calls need not carry it;
- **D — forbidden inference**: program must not synthesize it.

### 2.1 Root / clause structure

| Current field | Class | Ruling |
|---|---|---|
| `clauses` array ordering | A+B | ordering is model-owned; the literal wrapper name is protocol structure |
| clause `kind=mutate|wait` | B | can be discriminated structurally by `do` vs `wait`; no semantic choice is lost |
| mutation `verb` | A | action semantics belong to model |
| `target.kind=object|page` | B in current verbs | page/object class is mechanically implied by operation profile; do not ask model to repeat it unless needed for schema discrimination |
| `target.identity.kind` | A | part of exact semantic identity selected by model |
| `target.identity.name` | A | part of exact semantic identity selected by model |
| `target.identity.role` | A/optional | useful exact disambiguator when observed/needed; should not be required when kind+name is already unique |

### 2.2 Mutation arguments

| Current field | Class | Ruling |
|---|---|---|
| `click args={}` | B | pure structural noise; verb already fixes empty payload |
| `fill.text` | A | user/task semantic value |
| `fill.mode` | A encoded awkwardly | replace vs append is semantic, but can be encoded as explicit `set_text` vs `append_text` verbs instead of repeated mode field |
| `select.value` | A | semantic choice |
| `scroll.delta_pages` | A | semantic magnitude/direction |
| `navigate.url` | A | semantic destination |
| `navigate target={kind:page}` | B | page target is fixed by navigate operation |

### 2.3 Wait arguments

| Current field | Class | Ruling |
|---|---|---|
| wait target identity | A | model chooses what condition matters |
| `property` | A | semantic condition |
| `operator` | A in general | semantic comparison; common equality shorthand may encode it structurally |
| `value` | A | semantic expected value |
| `timeout_ms` | A/B | A only when deadline has task meaning; otherwise bounded runtime default should remove required model bookkeeping |
| `interval_ms` | B | polling cadence is mechanical in ordinary cases; use runtime default, not model round budget |

### 2.4 Fields the runtime already derives and must keep deriving

The model should not regain responsibility for:

- schema/domain constants;
- canonical scope ref;
- expected version;
- version scope;
- action id;
- physical target identity;
- single-dispatch / atomicity constants;
- before/after snapshot refs;
- current page resource ref created by internal observation;
- exact Predicate target/scope relations that follow from canonical grounding.

### 2.5 Forbidden program inference

The shorter interface must not introduce:

- best-match target selection;
- fuzzy name/role repair;
- “probably intended” object substitution;
- latest snapshot/ref substitution after stale state;
- automatic mutation retry/replay;
- semantic relevance or importance ranking;
- task success/completion judgment;
- alternate action selection after failure.

---

## 3. Output field classification

Current bounded operation returns a top-level receipt with a per-clause record; mutation clause records embed the complete underlying ActionReceipt.

### 3.1 What the model normally needs immediately

Keep in compact projection:

- execution status (`completed` / `halted` equivalent);
- number/index of steps executed;
- halt reason when halted;
- exact match count when target resolution blocked;
- final/new world version if mechanically observed;
- mechanically counted change summary when available;
- boundary event category when it forces a Semantic Decision Boundary;
- stable `receipt_ref` / `diff_ref` / `observation_ref` for exact hydration;
- explicit `automatic_retry=false` when ambiguity/replay safety matters;
- `task_completion=not_evaluated` or an equivalent unambiguous runtime contract.

### 3.2 What should remain durable but not be repeated on every success

Class C evidence-only candidates:

- full ActionReceipt revision history;
- full `scope_ref/action_id/receipt_id/receipt_seq` payload on ordinary success;
- full operation/idempotency/atomicity metadata when unchanged;
- full before/after grounding refs;
- full SemanticDiff object lists;
- full Predicate wire object after a satisfied wait;
- full observation bundle after a satisfied wait;
- verbose sensor/completeness provenance when no next decision depends on it.

These must remain exactly hydratable. Compact projection is not permission to discard evidence or replace it with semantic prose.

---

## 4. Quantitative baseline

### 4.1 FC2-C v0.2 first-call declaration gate

Source: local frozen `FC2C-FCR-ORNITH-v0.2`, six rows. This gate did **not** execute Browser actions; it measures declaration/first-call contract only.

Result:

- first-call oracle: **6/6 PASS**;
- first-call `get_tool_schema`: **0**;
- current serialized argument chars:
  - navigate: **120**;
  - fill: **180**;
  - wait: **190**;
  - mean: **163.3**.

A design-only shorthand example, with identical semantic intent but fewer structural fields, serializes to:

- navigate: **66** chars (**45.0%** lower);
- set_text: **92** chars (**48.9%** lower);
- wait enabled: **100** chars (**47.4%** lower);
- mean: **86.0** chars (**47.3%** lower than 163.3).

This is only a wire-size feasibility observation. It is **not** evidence that the proposed exact JSON grammar is already qualified.

### 4.2 FC2-B formal live baseline

Source: `FC2B-ORNITH-12-v0.1`, six rows.

- external task oracle: **3/6**;
- model rounds: **67 total**, mean **11.17** per task;
- tool calls: **65 total**;
- `browser_semantic_operation`: **31** calls;
- `get_tool_schema`: **7** calls;
- `read_evidence`: **27** calls;
- semantic-operation tool status: **17 success / 14 failure**;
- operation argument chars: **4,986 total**, mean **160.8**, median **155**, range **87..366**;
- successful operation argument mean: **181.3** chars;
- provider tokens in: **333,541**;
- provider tokens out: **11,489**;
- cache-hit tokens: **280,388**;
- automatic semantic-operation retry: **0**;
- runtime task-completion violation: **0**.

Interpretation:

- the architecture safety boundaries were not collapsing;
- however, a six-task run consumed 34 non-operation support calls (`schema + evidence`) in addition to 31 operation attempts;
- 14/31 operation attempts failed at the tool contract/surface level;
- this is exactly the class of interaction amplification MF aims to reduce.

Do not compare FC2-B task correctness directly to FC2-C FCR 6/6 as if they were the same gate: FC2-C v0.2 did not execute Browser actions.

---

## 5. Duplicate observation audit

Current `browser_semantic_execute` model-facing description says:

```text
read ActionReceipt -> browser_perceive(snapshot) -> Re-observe/Verify
```

But `BrowserActionAdapter.execute` already performs a post-dispatch capture and computes a diff, then places at least:

- `after_version`;
- `observed_effects.diff_ref`;
- after grounding ref;
- boundary events;
- completeness reasons

into the terminal ActionReceipt.

Ruling:

> A mandatory post-action model-visible snapshot is an interface tax when the already-produced post-capture/diff is sufficient for the next semantic decision.

This does **not** mean “never snapshot again”. A fresh explicit perception remains required when the compact post-action evidence is incomplete for the next decision, a structural boundary changed, or the model needs broader context.

---

## 6. Model-Declared Execution Horizon audit

Current `browser_semantic_operation` already supports the positive half of MDEH: multiple ordered clauses are model-declared, and the runtime does not invent/reorder clauses.

Missing first-class boundary:

- the runtime does not yet encode the new architecture rule “declared structural transition may continue; undeclared structural transition halts” as an explicit model-facing contract/gate;
- current ActionReceipt has `scope_transition_ref` placeholder behavior and boundary-event evidence, but MF-1 must freeze the exact halt semantics before implementation changes.

Therefore MF-1 must add deterministic RED cases for:

1. explicit `navigate` followed by exact target in new document -> mechanically eligible to continue;
2. ordinary click unexpectedly opens/replaces document/window -> halt before later clause;
3. target disappears -> halt;
4. target becomes ambiguous -> halt;
5. stale version -> halt;
6. dispatch outcome ambiguous -> halt/no replay;
7. satisfied wait -> continue;
8. unsatisfied/indeterminate wait -> halt;
9. clause exhaustion -> return with `task_completion=not_evaluated`.

---

## 7. SRTA baseline decision

For the frozen 3×2 Browser fixture, define the semantic decision-point denominator **from the task fixture, before looking at a model trajectory**.

Recommended first definition:

- a semantic decision point is a task-required choice of operation/target/value/condition that cannot be mechanically derived from the fixture’s already-declared prior choice;
- internal capture, grounding, version checks and wait samples are never model decision points;
- schema repair and evidence hydration caused only by interface protocol are model-facing amplification, not new semantic decisions.

MF-1 qualification harness should record both raw model-facing rounds and fixture-declared semantic decision points so SRTA can be computed without post-hoc interpretation.

Do not freeze a numeric SRTA pass threshold yet. First build the deterministic scorer and establish A baseline distribution.

---

## 8. MF-0 exit decision

MF-0 is complete enough to proceed to **MF-1 deterministic RED**, with these constraints:

1. first implementation variable is the model-facing compiler/projection, not Browser backend semantics;
2. no actuator rewrite;
3. no Predicate evaluator rewrite;
4. no weakening exact grounding/version/single-dispatch;
5. shorter input grammar must remain closed and structured;
6. compact output must preserve exact hydration of full evidence;
7. undeclared structural transitions require an explicit halt contract before multi-step batching is expanded;
8. live A/B waits until RED tests freeze authority boundaries.

No production implementation, deployment, restart or push occurred during MF-0.
