# FC2-C FCR v0.1 Result — NOT QUALIFIED

Implementation: `c6c3f612ae634d19d333ef047ecbd9109f9f8453`

Frozen experiment: `d13e07aad5baf389805092ed94385ab00b6bfb5c`

Final status: **NOT_QUALIFIED_BY_FC2C_FCR_V0.1**

## Result

The frozen single-Ornith first-call-ready matrix completed all 6 rows. The Gate is **FAIL: 4/6**. No Browser tool was executed in any row.

| Task | Result |
|---|---:|
| `navigate_page` | **2/2 PASS** |
| `fill_input` | **2/2 PASS** |
| `wait_button` | **0/2 FCR_FAIL** |
| Total | **4/6** |

Hard boundaries remained intact: `tool_execution_total=0`; `get_tool_schema` and `read_evidence` were not exposed; no fallback/second model/browser runtime participated in this Gate.

## What FC2-C closed

The canonical identity-vocabulary defect is closed by real model evidence, not only static tests. Both fill rows emitted the canonical identity `kind=input`, `role=textbox`, `name=Project code` on the **first** tool call and satisfied the frozen oracle. Page navigation also passed 2/2 on the first call.

This is a material improvement over FC2-B v0.1, where all 6/6 first bounded-operation calls were malformed before schema discovery.

## Remaining FCR defect

Both wait rows were otherwise mechanically correct and identical: `kind=wait`, exact button identity, `property=enabled`, `operator=eq`, boolean `true`, `timeout_ms=5000`, `interval_ms=250`. The sole contract violation was an additional field `verb:""`.

A mechanical counterfactual removed **only** that empty `verb`; both frozen wait calls then satisfied the pre-registered oracle. This is diagnostic evidence only and does not change the recorded v0.1 result.

Therefore the remaining defect is classified narrowly as **wait-clause field-boundary visibility**, not Browser runtime, grounding, wait sensing, mutation dispatch, or task-completion behavior. v0.1 must not be repaired in place; any fix requires a new protocol identity.

## Evidence identity

| Artifact | SHA256 | Bytes |
|---|---|---:|
| `execution-manifest.json` | `dc632bd9dd211251a276a4638ac096da4629521c878155ee0e053b0852e91721` | 3067 |
| `plan.json` | `6a1ff04233e5af4d8893ea6c1fcd7c4d37f7c7845097825340ddc62dd2a44dfe` | 965 |
| `results.jsonl` | `909f4f1dc90518484b97afc0b9610649f266485adb3d0882104a1d18049882a2` | 6126 |
| `fcr-gate.json` | `3e98f35af10f77e11c3cae70386cb166991242ee2d97bfe8116f5f4a2b57e867` | 509 |

Aggregate measured usage: input=9440, output=810, cache-hit=6258, summed wall=29.516s.

## Not claimed

This FCR protocol does not qualify live Browser execution, task completion, live grounding, mutation dispatch, runtime wait sensors, or cloud-provider schema compatibility.
