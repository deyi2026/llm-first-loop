# FC2-C FCR v0.2 Result — QUALIFIED (FCR ONLY)

Implementation: `3c1899de437b1d2b5f8a69cb25863263410440b7`

Frozen experiment: `e54ce3ce791ef6bba4cb65c670051d4e16545466`

Final status: **QUALIFIED_FCR_ONLY_BY_FC2C_V0.2**

## Result

The frozen single-Ornith first-call-ready matrix completed all 6 rows and the pre-registered Gate is **PASS: 6/6**. No Browser tool was executed in any row.

| Task | Result |
|---|---:|
| `navigate_page` | **2/2 PASS** |
| `fill_input` | **2/2 PASS** |
| `wait_button` | **2/2 PASS** |
| Total | **6/6 PASS** |

Hard boundaries remained intact: `tool_execution_total=0`; `get_tool_schema` and `read_evidence` were not exposed; no fallback, second model, Browser runtime, automatic retry, normalization, or completion judgment participated in this Gate.

## What changed from v0.1

The six-row plan, prompts, row order, external oracle, model/runtime contract, and strict full runtime schema are unchanged from v0.1. The generated plan SHA remains `c802cf5137511c28a6875421ab18233c7976b79c12f82a10e5af380e4559d59c`.

The only treatment change is provider-visible schema guidance mechanically derived from the strict full schema's `required` sets:

- mutate fields: `kind,verb,target,args`;
- wait fields: `kind,target,property,operator,value,timeout_ms,interval_ms`;
- wait explicitly has no `verb` / `args`.

No empty-verb normalization was added, no branch was reordered, and the strict runtime contract was not widened.

In v0.1, both wait rows were mechanically correct except for an extra `verb:""`, producing 4/6 overall. In v0.2 both wait rows omitted `verb` entirely and passed the unchanged oracle, raising the same matrix to **6/6**.

## Canonical identity result

The canonical vocabulary repair also remains live-qualified at the declaration layer: both fill rows emitted `kind=input`, `role=textbox`, `name=Project code` on the first tool call. This keeps `kind` aligned with perception's canonical `SemanticObject.kind` while `textbox` remains the role.

## Evidence identity

| Artifact | SHA256 | Bytes |
|---|---|---:|
| `execution-manifest.json` | `d792f80dab89a8b8759c8c80ff187f8c6748fe651671a298a85bd3f5b9c491b2` | 3083 |
| `plan.json` | `6a1ff04233e5af4d8893ea6c1fcd7c4d37f7c7845097825340ddc62dd2a44dfe` | 965 |
| `results.jsonl` | `6263c5576aa80b49bef4c2d33a9a469476bd1e1679a89609c60a7293b9634733` | 6020 |
| `fcr-gate.json` | `adb2fcf3ddda6b1bd17a55bed75413dc43850feec0d8cbdbcafff1c33f2750bd` | 489 |

Aggregate measured usage: input=9674, output=880, cache-hit=6414, summed wall=25.938s.

## Qualification boundary

This closes **First-Call-Ready/schema visibility** for the frozen single-Ornith declaration matrix only. It does not qualify live Browser execution, task completion, live grounding, mutation dispatch, runtime wait sensors, or cloud-provider schema compatibility. Those require a separate protocol identity and separate evidence.
