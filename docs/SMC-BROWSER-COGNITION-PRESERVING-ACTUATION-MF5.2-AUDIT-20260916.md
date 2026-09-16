# SMC Browser Cognition-Preserving Actuation — MF-5.2-A Surface Audit — 2026-09-16

Status: **READ-ONLY AUDIT COMPLETE / NO PRODUCTION EDIT IN THIS AUDIT**

Code inspected: `d6ec0113067a1107e6b703dc609fd681862964ae`

Design authority: `docs/SMC-BROWSER-COGNITION-PRESERVING-ACTUATION-MF5.2-PLAN-20260916.md`

## 1. Audit question

Does the current provider-visible `browser_semantic_operation` surface act like a natural execution affordance after the model has already decided what to do, or does it still ask the model to reshape task reasoning around execution protocol?

## 2. Current provider surface facts

At `d6ec0113`:

- description length: 401 chars;
- parameter schema: 3,845 serialized JSON chars;
- top-level required field: `steps`;
- six canonical action branches: `navigate`, `click`, `set_text|append_text`, `select`, `scroll`, `wait`;
- `wait` required fields: `do,target,property,value,within_ms`;
- optional wait field: `operator`;
- wait properties: `exists,enabled,checked,selected,expanded,focused,editable,name,value_text`;
- wait operators: `eq,contains,prefix,suffix,ge,le`.

`d6ec0113` correctly removes the prior special nested wait discriminator and mechanically compiles `do:"wait"` into the existing typed Predicate primitive. Exact target requirements and no-fuzzy/no-rebind/no-retry boundaries remain intact.

## 3. Field-by-field cognition audit

| Surface | Current role | Cognition assessment | Ruling |
|---|---|---|---|
| `do` | semantic action verb | genuine model decision | keep |
| target `kind` | semantic object class | genuine target identity | keep |
| target `name` | semantic object identity | genuine target identity | keep |
| target `role` | optional disambiguation | semantic only when needed | keep optional |
| `url/text/value` for normal actions | task-selected payload | genuine model decision | keep |
| top-level `steps` list | transport/batching container | mechanical; can imply pre-planning if description over-emphasizes batching | keep as transport for now, but explicitly make one action normal |
| `property` on wait | Predicate implementation vocabulary | often derivable from ordinary condition such as “button enabled” | hide for common states |
| `operator` on wait | Predicate implementation vocabulary | mechanical for common boolean/equality waits | derive by default; expose only advanced comparison escape hatch |
| `value=true` on wait | Predicate implementation vocabulary | mechanical when condition is “enabled/exists/checked/etc.” | derive from natural state condition |
| `within_ms` | bounded polling control | usually mechanical unless user/task gives a real deadline | make optional with bounded runtime default; model supplies only when semantically meaningful |
| internal polling interval | runtime mechanic | no model semantic value | remain hidden |
| scope/version/action id | runtime mechanic | no model semantic value | remain hidden |
| receipt/diff internals | evidence | useful only on demand | keep compact + exact hydrate |

## 4. Residual cognition pressure

### 4.1 Description currently nudges planning

Current description starts with:

> `模型一次声明1..8个 ordered steps`

This is mechanically true but cognitively misleading. It can make the model treat a multi-step execution horizon as a preferred planning format.

Required correction:

> One already-decided action is normal. Multiple actions may be handed off together only when the model has already decided them naturally.

MDEH is optional batching, not a planning protocol.

### 4.2 Wait still leaks Predicate DSL

After `d6ec0113`, syntax is regular but a simple thought:

> wait until “Finalize after ready” is enabled

still becomes:

```json
{
  "do":"wait",
  "target":{"kind":"button","name":"Finalize after ready"},
  "property":"enabled",
  "value":true,
  "within_ms":60000
}
```

and may additionally require `operator` for non-default comparisons.

The model is being asked to translate an ordinary condition into the runtime's Predicate vocabulary. That is smaller than the old contract, but it is still protocol work.

Recommended common-state affordance:

```json
{
  "do":"wait",
  "target":{"kind":"button","name":"Finalize after ready"},
  "until":"enabled"
}
```

Mechanical compiler:

```text
until=enabled
  -> property=enabled
  -> operator=eq
  -> value=true
  -> bounded runtime default timeout/poll interval
```

This is not semantic inference. The mapping is a closed deterministic alias from one explicit state condition to the already-qualified Predicate wire.

### 4.3 Mandatory timeout leaks scheduler mechanics

MF-5 delayed-wait success used `within_ms=60000`, but the user task did not specify a 60-second semantic deadline. The model selected a runtime control value because the schema demanded one.

Ruling:

- common wait call: timeout optional;
- runtime supplies a bounded documented default;
- if the task/user specifies a meaningful deadline, model may override explicitly;
- timeout default must be deterministic and visible in the receipt/evidence.

## 5. Natural affordance without opaque NLP

Cognition preservation does not require a free-form natural-language parser.

A closed action vocabulary can still be natural:

```json
{"do":"click","target":{"kind":"button","name":"Save"}}
```

```json
{"do":"set_text","target":{"kind":"input","name":"Project code"},"text":"AB-7319"}
```

```json
{"do":"wait","target":{"kind":"button","name":"Finalize after ready"},"until":"enabled"}
```

The model chooses action/target/business payload. The runtime only expands closed aliases into exact qualified mechanics.

## 6. Proposed wait surface split

Do not expose the full Predicate algebra on every ordinary wait.

### 6.1 Common state wait

Provider-facing canonical path:

```json
{
  "do":"wait",
  "target":{"kind":"button","name":"Save"},
  "until":"enabled"
}
```

Candidate closed `until` enum:

- `exists`
- `enabled`
- `checked`
- `selected`
- `expanded`
- `focused`
- `editable`

Each is deterministically compiled to `property=<state>, operator=eq, value=true`.

### 6.2 Advanced comparison wait

Text/value comparisons remain semantically richer and may require explicit comparison structure. Keep them as a separate strict branch/escape hatch, for example:

```json
{
  "do":"wait_value",
  "target":{"kind":"status","name":"Build status"},
  "field":"value_text",
  "contains":"Ready"
}
```

The exact final spelling is not frozen by this audit. The design requirement is that common state waits do not force the model through a generic Predicate DSL merely for implementation symmetry.

## 7. Observable Gate implications

MF-5.2 should treat these as failures even if the external task eventually succeeds:

- schema lookup only to learn ordinary action grammar;
- repeated same-intent calls differing only in tool grammar;
- model adds unrelated actions to make wait accepted;
- model retries a canonical common wait with Predicate scaffolding after a contract rejection;
- model batches extra future actions solely because the description implies multi-step planning is expected.

Do not penalize genuine task reconsideration after an SDB.

## 8. Recommended deterministic RED set

Before production change, write RED tests for:

1. provider wait common branch accepts `do,target,until` with no mandatory timeout;
2. `until=enabled` compiles exactly to `property=enabled, operator=eq, value=true`;
3. `until=exists` and other closed state aliases compile mechanically;
4. runtime default timeout/poll values are deterministic and surfaced in durable receipt/evidence;
5. explicit semantic timeout override remains supported;
6. exact `kind+name` target is still mandatory;
7. no target inference/fuzzy/best-match/rebind/retry is introduced;
8. one-action `steps` call is fully valid for every action family;
9. tool-local description says single action is normal and batching is optional;
10. legacy typed Predicate branch remains internal/compatibility as needed, not the required common model path.

## 9. Audit verdict

`d6ec0113` fixes the largest MF-5 grammar asymmetry but is **not yet cognition-preserving by construction**.

The remaining high-value correction is narrow:

> **Move common wait Predicate bookkeeping and default timing out of the model-facing contract, and stop presenting multi-step batching as the model's preferred planning mode.**

No grounding, authority, actuator, retry or task-completion semantics need to change.
