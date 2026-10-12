# SMC Rule Authority v0.1

> Status: **P0 / docs-only / shadow design**
> Baseline: `main@19e253edfe4d3fcbeb268830b90d00fd273a6262`
> Production consumption: **none**
> Purpose: freeze which semantic relations may be mechanically derived, which may later gate execution, and which must remain model/runtime owned.

## 1. Core ruling

SMC Semantic Logic is **not** a planner, semantic router, task judge, permission system, or execution engine.

Its allowed role is narrower:

> After a model or caller has selected a semantic subject/condition/action, derive only relationships that are already mechanically determined by grounded facts and frozen contracts.

The authority split is:

| Layer | Owns | Must not own |
|---|---|---|
| LLM | target relevance, semantic condition, action choice, strategy, task completion | scope/version bookkeeping, runtime fences |
| Semantic Logic | deterministic semantic closure, source/conflict/coverage closure, derivation proof | target selection, recommendation, completion, retry strategy |
| Adapter | physical observation, raw grounding, physical dispatch primitives | task meaning, best target, hidden semantic arbitration |
| Runtime | permission, effect authority, locks, reservations, idempotency enforcement, durable append, process/session ownership | task relevance, semantic goal selection |

This split preserves LLM-First: programmatic layers provide factual and mechanical structure, while the model retains semantic agency.

## 2. Authority classes

Every future Rule MUST declare exactly one `authority_class`.

### 2.1 `observation_projection`

Transforms adapter observations into canonical fact shape without adding new world meaning.

Examples:

- DOM source record -> source-qualified `enabled=true` fact;
- snapshot metadata -> `scope_ref`, `observed_version`, sensor contract facts;
- file snapshot -> byte hash/version fact.

May be consumed by shadow and later production projections.

### 2.2 `mechanical_derivation`

Pure derivation from already-grounded facts and closed contracts.

Examples:

- exact object `GroundingRef` -> object id + scope_ref + observed_version;
- scope predicate -> `target=scope_ref`;
- object ref + chosen property/operator/value -> full canonical Predicate;
- conflicting source facts without a deterministic resolver -> canonical value `null` + unresolved conflict;
- incomplete relevant coverage + missing object -> `indeterminate`, not `false`.

This is the primary target for the Semantic Logic Layer.

### 2.3 `execution_precondition_fact`

Produces a mechanical eligibility fact that MAY later be consumed by Runtime, but only after an explicit selective-authority qualification phase.

Examples:

- version assessment `match|stale|indeterminate`;
- exact target belongs to exact scope;
- GroundingRef still available and session-authorized;
- verb contract requires `object` or `resource` version scope.

P0/P1/P2/P3 output in this class remains **shadow-only**.

### 2.4 `runtime_authority`

Hard execution authority. This is **not transferable** to the semantic rule engine.

Examples:

- session/run ownership;
- effect mutation authority;
- path lock / process lock;
- action-id reservation;
- durable receipt append;
- filesystem atomic replace;
- permission/authentication;
- actual physical dispatch.

Semantic Logic may describe these facts when Runtime emits them, but MUST NOT manufacture or substitute them.

### 2.5 `model_semantic`

Semantic choices reserved for the model/user.

Examples:

- which object matters;
- which property to inspect;
- whether waiting is useful;
- whether to click/fill/navigate;
- whether a satisfied Predicate means the user task is complete;
- whether a historical fact is relevant to the present task;
- whether one strategy is better than another.

Rules in this class are forbidden from production RulePack authority.

### 2.6 `candidate_only`

Model-authored or experimentally proposed rules live here until independently reviewed and qualified.

`candidate_only` output MUST NOT gate routing, dispatch, retry, completion, or authority.

## 3. Closed forbidden semantic outputs

Production-capable RulePacks MUST NOT emit fields or predicates equivalent to:

```text
important
priority
recommended
best
preferred
task_relevant
should_click
should_fill
should_navigate
next_action
recovery_sequence
likely_complete
task_complete
goal_complete
user_intent_is
```

Aliases or namespaced variants with the same authority meaning are equally forbidden.

## 4. Current Browser ownership map

### 4.1 Candidate for `mechanical_derivation`

| Current behavior | Current owner | Future logic candidate |
|---|---|---|
| GroundingRef -> object/scope/version | `browser_semantic_execute.py`, `browser_wait.py` | yes |
| scope Predicate target equals scope_ref | `browser_wait.py`, `predicate.py` | yes |
| object Predicate target/scope from exact ref | `browser_wait.py` | yes |
| DOM/AX conflict -> null + source evidence | `browser/perception.py` | yes |
| partial coverage + negative absence -> indeterminate | `browser/predicate.py` | yes |
| diff comparability from scope/sensor lineage | `browser/perception.py` | yes |
| object/resource version relation | `browser/perception.py` | yes |
| semantic action fixed fields | `browser_semantic_execute.py` | yes |

### 4.2 Must remain Runtime/Adapter owned

| Behavior | Owner |
|---|---|
| session fencing and durable store access | Runtime/store |
| action_id reservation | `BrowserActionReceiptStore` |
| current effect mutation authority | Runtime journal authority |
| actual DOM/CDP dispatch | Browser actuator |
| post-dispatch capture | Browser adapter/control plane |
| receipt fsync/append | Runtime/store |
| physical target locator resolution | Browser adapter private grounding |

### 4.3 Must remain Model owned

- choose `Submit` rather than `Cancel`;
- choose `enabled` rather than `name`;
- choose `click` rather than `wait`;
- decide whether to re-observe after a rejection;
- decide whether an `ok` ActionReceipt satisfies the user's objective.

## 5. Perceive / Operate boundary

Semantic Logic MUST NOT decide whether a user request belongs to Perceive or Operate.

It MAY state closed capability facts such as:

```text
Perceive -> operation_class=observe
Operate -> operation_class=mutate
object mutation -> requires exact object grounding
navigate -> requires exact resource grounding
```

Once the model selected a capability, the Logic Layer may remove redundant synthesis burden. It does not own capability selection.

## 6. Rule lifecycle

Every rule follows:

```text
candidate
  -> deterministic_tested
  -> shadow_qualified
  -> authority_eligible
  -> active
  -> superseded | retired
```

P0 freezes only specification metadata. No P0 rule is `authority_eligible` or `active`.

Required metadata:

```text
rule_id
rule_version
rulepack_id
domain
authority_class
inputs
outputs
closed_world_requirements
source_refs
fixture_refs
rule_hash
status
```

## 7. Shadow boundary

Until a later explicit cutover phase, Semantic Logic output MUST NOT be consumed by:

- provider/model routing;
- tool selection;
- task completion;
- mutation dispatch;
- automatic retry/rebind;
- permission/admission;
- resource governance;
- ActionReceipt status;
- user-visible canonical result.

Allowed P0-P3 consumers:

- offline comparison;
- deterministic qualification;
- mismatch reporting;
- derivation/proof inspection;
- performance measurement.

## 8. Promotion gates for execution-precondition rules

An `execution_precondition_fact` can become Runtime-consumable only if all are true:

1. frozen input contract exists;
2. Python canonical oracle is identified;
3. shadow equivalence is 100% for deterministic corpus;
4. adversarial unknown/conflict cases produce no false closure;
5. no model-owned field is introduced;
6. no silent refresh/rebind/retry exists;
7. rulepack hash/version is runtime-visible;
8. rollback to prior Python authority is mechanical;
9. separate human/owner authorization occurs for cutover.

## 9. Fail-closed meaning

`fail-closed` applies only to the claimed mechanical authority.

Examples:

- unknown GroundingRef -> cannot prove exact target binding;
- missing rule version -> cannot use that rule for dispatch eligibility;
- ambiguous identity -> cannot claim target continuity.

It MUST NOT be inflated into semantic claims such as:

```text
the user cannot complete the task
no useful action exists
the target is irrelevant
```

## 10. P0 ruling

P0 freezes the following architecture decision:

> SMC Semantic Logic may own deterministic semantic closure, but not semantic choice or physical/runtime authority.

This document is itself non-executable and non-authoritative for production until a later explicitly qualified implementation references a versioned/hash-pinned RulePack.
