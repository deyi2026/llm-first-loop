# SMC Browser Cognition-Preserving Semantic Actuation — MF-5.2 v0.2 Result — 2026-09-16

Status: **COMPLETE / NOT QUALIFIED / SAFETY PASS / COGNITION-PRESERVING GATE FAIL / MF-6 DEFERRED**

Experiment Git HEAD: `bfac4cdede492ad5c0f8d28680eaa6759a0cd884`

Model-facing implementation anchor: `ab99aac3d6287a485f4d45646287242bc6a6ab07`

Protocol identity: `smc.browser_cognition_preserving_actuation_mf52.v0.2`

Measured result set: `evals/browser_smc_cognition_preserving_actuation_mf52/results/MF52-ORNITH-v0.2-MEASURED-bfac4cde/`

## 1. Verdict

MF-5.2 v0.2 is **NOT QUALIFIED** under the frozen treatment Gate.

The strongest result is not merely that the Gate failed. The evidence separates three different layers that had previously been conflated:

1. **mechanical Browser safety remains healthy**;
2. **model-facing protocol friction is still material**;
3. **even zero protocol-repair does not guarantee an effective task trajectory when the model lacks a natural perception/verification surface**.

Therefore the next correction must not be “teach the model the Semantic Operation DSL better”. It should make the model-facing surface match the model's natural cognitive loop:

```text
perceive when understanding is needed
  -> model reasons normally
  -> model decides one action
  -> semantic runtime actuates mechanically
  -> compact local delta
  -> perceive again only when the next semantic decision needs broader world state
```

## 2. v0.1 invalid infrastructure attempt is preserved

The earlier MF-5.2 v0.1 measured attempt at experiment HEAD `d4029f55...` is **not model-behavior evidence** and is not replayed or overwritten.

Rows 1-2 both reached external browser oracle PASS, but the worker crashed after model execution with the same harness-only error:

`KeyError('undeclared_boundary_continuation_count')`

Root cause: the harness attempted to infer declared-vs-undeclared Browser boundary behavior from the compact model receipt. A successful `navigate` legitimately carries a boundary event, so compact output does not retain enough clause context for that classification. v0.2 fixes only the measurement path: structural-boundary qualification is read exclusively from the durable full operation receipt, where the clause verb is available.

No model-visible schema, task prompt, fixture, Browser execution semantic, Gate threshold or production implementation changed between the invalid v0.1 attempt and v0.2.

## 3. Frozen v0.2 Gate result

| Gate item | Result |
|---|---:|
| Complete measured rows | 6/6 |
| Infrastructure valid | PASS |
| Exact provider surface | PASS |
| Fallback used | 0 |
| External task oracle | **3/6 — FAIL** |
| Per-task oracle | click 1/2; fill 2/2; delayed-wait 0/2 |
| First semantic-operation contract valid | **5/6 — FAIL** |
| Operation tool FAILURE | **18 — FAIL** |
| Operation tool ERROR | 0 |
| `get_tool_schema` | **2 — FAIL** |
| Observable protocol-repair episodes | **20 — FAIL** |
| Automatic mutation retry | 0 |
| Direct hidden atomic Browser calls | 0 |
| Runtime task-completion judgment | 0 |
| Undeclared boundary continuation | 0 |
| SecurityAgent spawned | false |

Frozen result: `pass=false`.

MF-6 independent confirmatory must remain deferred.

## 4. Per-row evidence

| Row | Task | Oracle | Rounds | Semantic ops | Protocol repair |
|---:|---|---|---:|---:|---:|
| 1 | click_commit r1 | PASS | 12 | 6 | 5 |
| 2 | fill_submit r1 | PASS | 12 | 9 | 5 |
| 3 | delayed_wait r1 | FAIL | 12 | 8 | 3 |
| 4 | delayed_wait r2 | FAIL | 12 | 12 | **0** |
| 5 | fill_submit r2 | PASS | 12 | 9 | 4 |
| 6 | click_commit r2 | FAIL | 12 | 9 | 3 |

Two rows are especially diagnostic:

- **delayed_wait r2:** zero contract/schema repair, yet the task still failed. The model issued syntactically valid semantic operations but repeatedly grounded guessed page/text objects that did not exist.
- **click_commit r2:** the target button was clicked twice; oracle ended with `commit_count=2`. The first click mechanically succeeded, but the model lacked a natural semantic verification path and later re-navigated/repeated the action.

## 5. Interface-friction taxonomy

There were 18 contract failures:

| Failure | Count | Interpretation |
|---|---:|---|
| `short_target_fields_mismatch` | **16** | model repeatedly tried natural page/document waits that the object-target contract cannot express |
| `steps_count_out_of_bounds` | 1 | model emitted one direct action object under `steps` instead of wrapping it in an array |
| `wait_until_not_supported` | 1 | model used natural `until="loaded"`, while the closed object-state vocabulary has no page-ready condition |

This is a different failure generation from MF-5 v0.1. The old one-off wait discriminator is fixed; the remaining dominant mismatch is **scope/page semantics leaking through an object-only target surface**.

## 6. Valid-syntax grounding probes are the second failure class

In addition to 18 contract failures, there were **14 mechanically valid semantic-operation results halted with `target_not_found`**.

The strongest example is delayed_wait r2:

- protocol repair = 0;
- 12 valid semantic-operation calls;
- 9 `target_not_found` halts;
- repeated exact identities such as document/page and text/Ready variants;
- the exact button `Finalize after ready` was found with `until=exists`, but the model never converted that observation into the final `until=enabled -> click` trajectory before the round ceiling.

This is not a reason to add fuzzy/best-match grounding. Exact fail-closed behavior worked correctly. The problem is that the model was using actuation calls as a surrogate for **perception and state discovery**.

Future qualification should record a separate diagnostic such as **Grounding Probe Amplification**: repeated valid calls that only test guessed semantic identities and return `target_not_found`. This must not retroactively change the v0.2 Gate.

## 7. Single-action behavior falsifies “batch-first” as the model default

Across the six rows:

- total semantic-operation calls: 53;
- recognized single-action calls: **52**;
- multi-action calls: **0**;
- one malformed first call put a single action object directly under `steps` instead of an array.

Observed verb mix:

- `wait`: 31;
- `navigate`: 9;
- `click`: 6;
- `wait_text`: 4;
- `set_text`: 2.

The data strongly supports the cognition-preserving ruling:

> **One already-decided action is the natural default. MDEH batching is an optional handoff optimization, not the primary model-facing planning format.**

The next design should audit making a single action the top-level normal form instead of forcing every action through a `steps:[...]` container. Optional batching may remain available only when the model has naturally already decided multiple actions.

## 8. Perception is a cognitive dependency, not mechanical overhead

The treatment exposed exactly three tools: semantic operation, schema lookup and Evidence read. `browser_perceive` was intentionally hidden to isolate actuation.

The result shows that this surface is too narrow for the intended architecture.

After navigation or mutation, the model often needs to understand the current semantic world before deciding what to do next. That is a genuine **cognitive dependency**. It must not be “optimized away” merely to reduce tool rounds.

Observed consequences of the operate-only surface include:

- repeated document/page existence probes after navigation;
- text-object guesses such as `Ready`, `Status`, `Not ready`, `confirmation`;
- successful mutations followed by more page/document probes instead of confident termination;
- delayed_wait r1 reaching a successful exact `wait(button, enabled)` only at the final round, leaving no round for the required click;
- click_commit r2 repeating a successful click and ending with `commit_count=2`.

This reinforces the earlier two-surface direction:

1. **Perceive** — when the model needs to understand an unknown or materially changed world;
2. **Actuate** — when the model has already decided an action.

The runtime may internally observe before/after an action for mechanical grounding/diff, but that does not eliminate a model-visible perception turn when the next semantic decision genuinely requires broader world context.

## 9. Compact receipts remain useful but are not a substitute for perception

MF-3's compact result principle remains valid:

`durable full evidence -> compact mechanical projection -> exact hydrate`

But v0.2 shows a boundary:

> a compact mechanical receipt can prove that an action was dispatched and report local change facts; it cannot decide which world facts the model needs for its next semantic judgment.

Therefore the architecture should not require a blanket post-action snapshot, but it must keep a natural perception affordance available when the model decides it needs to inspect the world.

## 10. Efficiency/observability facts

Aggregate diagnostics:

- agent rounds: 72 (all six rows reached the 12-round ceiling);
- semantic-operation calls: 53;
- `read_evidence`: 17;
- `get_tool_schema`: 2;
- model-visible operation argument chars: 5,372;
- model-visible operation result chars: 17,162;
- input tokens: 253,962;
- output tokens: 8,526;
- cache-hit tokens: 239,372;
- multi-action calls: 0.

The low serialized operation bytes are therefore not sufficient evidence of cognitive efficiency. **Interface bytes decreased while semantic trajectory amplification remained high.**

## 11. Safety result

The following hard boundaries remained intact across all six rows:

- no fuzzy/best-match target repair;
- no program target substitution;
- no automatic latest/rebind;
- no automatic mutation retry/replay;
- no hidden atomic Browser tool calls;
- no program task-completion judgment;
- no undeclared structural-boundary continuation;
- no provider fallback;
- zero operation execution errors.

The next design correction must preserve all of these.

## 12. Required next identity: MF-5.3 read-only architecture audit first

Do **not** immediately add more syntax or rerun MF-6.

MF-5.3 should begin as a read-only design/audit phase with four questions:

1. **Perception companion:** can the existing `browser_perceive` be exposed in a smaller model-friendly form so the model can inspect unknown state without using `wait` as a probe?
2. **Single-action-first actuation:** can the normal call be direct `do/target/...`, with optional batching only as a secondary already-decided horizon?
3. **Natural scope waits:** how should page/scope conditions such as ready/url be expressed without inventing fake document objects and without exposing internal scope/version bookkeeping?
4. **Post-action sufficiency:** what minimal local delta should an actuation receipt return, and when must the model explicitly perceive broader state?

Only after these contracts are frozen should deterministic RED tests or production edits begin.

## 13. Evidence identity

### v0.2 formal qualification

| Artifact | SHA-256 |
|---|---|
| `execution-manifest.json` | `50de33c632497a834d6b05d88ed7ac29f437b7e1370b024bb48e6ca1ed9e084a` |
| `plan.json` | `77eb31a252fd551ebcd6774cd4bd9f4c19a36f8e44cd8e665e0f4f53931f5418` |
| `results.jsonl` | `8078186441b8a29cab92485e05fdb9d7cdcd62c05157c3efc15f060a39cfc1f5` |
| `qualification-gate.json` | `cd2441a257b9a67dbc401d72632ca9bb49cfa4ee01d92715ee8253bd8d0d066f` |

### v0.1 invalid attempt

| Artifact | SHA-256 |
|---|---|
| `execution-manifest.json` | `8b9e2a5b8b2dd88488173d80be9e0ab719f9fbaf13cf475b561c59d99fa573e2` |
| `plan.json` | `77eb31a252fd551ebcd6774cd4bd9f4c19a36f8e44cd8e665e0f4f53931f5418` |
| `results.jsonl` | `a71cb4e4bdb6d86804945704ed8a1a54db3eb20684b0b19b5d6932efc26aa97a` |

No production deployment, service restart, cloud fallback or second local model was used.
