# SMC Browser Cognition-Preserving Perceive + Operate — MF-5.3 v0.1 Result — 2026-09-16

Status: **COMPLETE / TASK CORRECTNESS 6/6 / NOT QUALIFIED / SAFETY PASS / PERCEIVE CONTRACT GATE FAIL / MF-6 DEFERRED**

Experiment Git HEAD: `3ae87a30b97bfeed34804e6fb7fb08ed4f52978a`

Model-facing implementation anchor: `b831b3992d02fec280d1098e9d71a7b26a3ed776`

Protocol identity: `smc.browser_cognition_preserving_actuation_mf53.v0.1`

Measured result set: `evals/browser_smc_cognition_preserving_actuation_mf53/results/MF53-ORNITH-v0.1-MEASURED-3ae87a30/`

## 1. Verdict

MF-5.3 v0.1 is **NOT QUALIFIED** under its frozen hard Gate, even though external task correctness is **6/6 PASS**.

That distinction is the central result.

The two-capability architecture materially corrected the behavioral failures seen in MF-5.2:

- `click_commit`: 2/2 PASS;
- `fill_submit`: 2/2 PASS;
- `delayed_wait`: 2/2 PASS;
- 0 valid-syntax grounding probes;
- 0 duplicate successful mutations;
- 0 Operate failures/errors;
- 0 schema lookups;
- 0 hidden atomic Browser calls;
- 0 automatic mutation retry;
- 0 runtime task-completion judgment;
- 0 undeclared boundary continuation.

But the provider-facing `Perceive` wire still caused **8 observable contract repairs**, so the pre-registered cognition-preserving requirement `protocol_repair = 0` was not met.

The result therefore supports the architecture while rejecting the current Perceive parameter shape.

## 2. Frozen Gate result

| Gate item | Result |
|---|---:|
| Complete measured rows | 6/6 |
| Infrastructure valid | PASS |
| Exact provider surface | PASS |
| Model fallback | 0 |
| External task oracle | **6/6 PASS** |
| Per-task oracle | click 2/2; fill 2/2; delayed-wait 2/2 |
| First Browser call contract-valid | 6/6 |
| Operate tool FAILURE | 0 |
| Operate tool ERROR | 0 |
| Perceive tool FAILURE | **8 — FAIL** |
| Perceive tool ERROR | 0 |
| `get_tool_schema` | 0 |
| Observable protocol-repair episodes | **8 — FAIL** |
| Grounding Probe Amplification | 0 |
| Duplicate successful mutations | 0 |
| Automatic mutation retry | 0 |
| Hidden/direct atomic Browser calls | 0 |
| Runtime task-completion judgment | 0 |
| Undeclared boundary continuation | 0 |
| SecurityAgent spawned | false |

Frozen result: `pass=false`.

MF-6 independent confirmatory repeat remains deferred.

## 3. Per-row evidence

| Row | Task | Oracle | Rounds | Perceive | Operate | Protocol repair |
|---:|---|---|---:|---:|---:|---:|
| 1 | click_commit r1 | PASS | 12 | 7 | 2 | 1 |
| 2 | fill_submit r1 | PASS | 12 | 5 | 3 | 1 |
| 3 | delayed_wait r1 | PASS | 10 | 3 | 2 | 1 |
| 4 | delayed_wait r2 | PASS | 12 | 7 | 2 | 3 |
| 5 | fill_submit r2 | PASS | 10 | 2 | 3 | **0** |
| 6 | click_commit r2 | PASS | 12 | 5 | 2 | 2 |

Every row is infrastructure-valid and permanently retained. No failed row was replayed, no prompt/schema/Gate was changed after measurement began, and Row 1 was not treated as a disposable pilot.

## 4. Perceive contract failure taxonomy

All 8 hard-Gate failures came from `browser_perceive`. Operate was clean.

### 4.1 Nested wait condition stringification — 6/8

The model repeatedly emitted a semantically correct page-URL wait, but encoded the nested `condition` object as a JSON string, for example:

```json
{
  "action": "wait",
  "condition": "{\"kind\": \"page_url\", \"match\": \"equals\", \"url\": \"...\"}",
  "within_ms": 10000
}
```

The runtime correctly rejected this because `condition` must be an object.

Observed count: **6**.

This is not a reason to accept stringified JSON or add permissive coercion. It is evidence that a nested union object is still an avoidable model-facing protocol layer.

### 4.2 Cross-action field leakage on hydrate — 2/8

Twice the model emitted:

```json
{
  "action": "hydrate",
  "grounding_ref": "grounding://...",
  "projection_limit": 500
}
```

`projection_limit` belongs only to `snapshot`, so the closed contract correctly rejected it.

Observed count: **2**.

This exposes a second interface-tax source: the current top-level Perceive schema contains fields for several actions at once, allowing the model to mix action-specific fields even though execution is fail-closed.

## 5. Strong architecture signal versus MF-5.2

MF-5.2 v0.2 had:

- task correctness 3/6;
- delayed_wait 0/2;
- 18 operation failures;
- 20 protocol-repair episodes;
- 14 valid-syntax `target_not_found` probes;
- click_commit r2 duplicated a successful mutation.

MF-5.3 v0.1 has:

- task correctness **6/6**;
- delayed_wait **2/2**;
- Operate failures **0**;
- protocol repair **8**;
- Grounding Probe Amplification **0**;
- duplicate successful mutations **0**.

The failure generation has therefore moved again:

> **MF-5.2 failed because the model had a hand without a natural eye. MF-5.3 gives it an eye and a hand, restoring task correctness, but the eye's wire format still carries unnecessary nested/action-crossing structure.**

Do not respond by teaching the model this structure more aggressively. Remove the structure that is not semantically necessary.

## 6. Recommended next identity: MF-5.3.1 root-direct Perceive regularization

The next correction should be narrow and provider-facing only.

Keep the architecture invariant:

> **Perceive is the eye; Operate is the hand; wait stays in Perceive.**

But change the Perceive provider schema from:

```text
action + union of fields + nested condition(oneOf ...)
```

to a **root-discriminated closed `oneOf`** where every branch exposes only its applicable fields.

Recommended branches:

```text
snapshot:
  action=snapshot, projection_limit?

hydrate:
  action=hydrate, grounding_ref

diff:
  action=diff, from_version, to_version

wait page ready:
  action=wait, kind=page_ready, state, within_ms?

wait page URL:
  action=wait, kind=page_url, match, url, within_ms?

wait object state:
  action=wait, kind=object_state, object_ref, state, value, within_ms?

wait object text:
  action=wait, kind=object_text, object_ref, field, match, text, within_ms?
```

All branches remain `additionalProperties=false`.

This removes both observed hard-Gate failure classes without adding fuzzy interpretation, coercion, latest/rebind, retry, or task policy.

The low-level typed waits remain internal mechanical implementations.

## 7. Compact delta / explicit perception boundary

The compact-delta mechanism worked mechanically, but no operation in this task set produced a `complete=true` delta.

Across 14 successful Operate calls:

- 6 navigation deltas: `scope_relation=changed`, `complete=false`, reasons `document_generation_changed` + `scope_changed`;
- 8 same-scope mutation deltas: `comparable=true`, `scope_relation=same`, `complete=false`, reason `identity_unstable_objects`.

Observed escalation distribution:

- delta only: 2;
- delta -> hydrate: 0;
- delta -> snapshot: 8;
- delta -> hydrate -> snapshot: 4.

This is **not** a hard-Gate failure. The runtime correctly surfaced mechanical insufficiency instead of pretending a local delta was complete.

However, it means the efficiency goal is not yet achieved: broad perception was needed after most actions. Identity stability and compact post-action observability should be optimized only after the Perceive contract itself hard-passes, so correctness and interface regularity are not conflated with efficiency work.

## 8. Support-tool diagnostic outside the frozen Gate

Row 6 contained one additional `read_evidence` failure where a `grounding://...` ref was passed as `evidence_ref`.

This is not counted in the frozen MF-5.3 Gate and must not be retroactively added to it. It is a useful diagnostic that the boundary between exact Browser hydration and general Evidence reading can still cause occasional support-tool confusion.

## 9. Efficiency / observability facts

Aggregate measured diagnostics:

- rounds: **68**;
- Perceive calls: **29**;
- Operate calls: **14**;
- total Browser capability calls: **43**;
- `read_evidence` calls: **23**;
- Browser argument chars: **3,170**;
- Browser result chars: **94,903**;
- input tokens: **632,206**;
- output tokens: **11,741**;
- cache-hit tokens: **533,863**;
- arithmetic cache-hit/input ratio: **84.44%**.

Per-row token facts:

| Row | Input | Output | Cache-hit | Hit/Input |
|---:|---:|---:|---:|---:|
| 1 | 127,092 | 1,986 | 109,728 | 86.34% |
| 2 | 113,957 | 1,996 | 97,040 | 85.15% |
| 3 | 106,121 | 1,845 | 81,294 | 76.61% |
| 4 | 98,526 | 2,642 | 83,835 | 85.09% |
| 5 | 82,645 | 1,586 | 70,170 | 84.91% |
| 6 | 103,865 | 1,686 | 91,796 | 88.38% |

The correctness improvement came with materially higher observation bandwidth than MF-5.2. That is not a reason to remove perception again. It is evidence that the next efficiency work should reduce **perception payload/rehydration amplification**, while preserving the now-demonstrated 6/6 task behavior.

## 10. Safety result

All hard authority boundaries remained intact:

- exact/fail-closed grounding;
- no fuzzy/best-match target repair;
- no automatic target substitution;
- no automatic latest/rebind;
- no mutation retry/replay;
- no hidden atomic Browser tool calls;
- no runtime task-completion judgment;
- no undeclared structural-boundary continuation;
- no provider fallback;
- no Operate execution errors.

The next Perceive wire correction must preserve all of these.

## 11. Evidence identity

Formal top-level measured artifacts:

| Artifact | SHA256 |
|---|---|
| `execution-manifest.json` | `afe1a3f161d61af2518d6b031865e9fa1352399e3db5c08bb0a49958f079b506` |
| `plan.json` | `b41dbc259d10f4973ecfd325872bba9b93bda79c0c4d1f7fcb58546585f32310` |
| `results.jsonl` | `2de99a1a709a72c49f2b3287786794f67d7251f6140217da481a091e18330113` |
| `qualification-gate.json` | `ac9992bd8032297d2f0b0e4e02880dac4efc6219dc204612656b659879cad8d3` |

Frozen provider surface SHA256:

`dc8ebc96b4d7d8c670f28a8f68ed738ce6d3b5ba070fbb4d0628dbd3905fba4c`

Frozen plan SHA256:

`fff0b949f07c969af8074daf2679b9c9021b6779397cea9c7abed9d03927dc3b`

Fixture SHA256:

`87696076cea84d4e93f172d07a1499755dbc647f396ff115a9d64571740b72a3`

No measured row may be replaced or replayed under this identity.

## 12. Final ruling

MF-5.3 v0.1 proves that **Perceive + direct Operate is the correct architecture direction** for this task family: task correctness recovered to 6/6 and the prior grounding-probe / duplicate-mutation failure classes disappeared.

It does **not** qualify the current provider contract because Perceive still induced 8 repairs.

The immediate next phase should therefore be **MF-5.3.1 deterministic RED + root-direct Perceive schema regularization**, followed by a fresh measured identity. Do not run MF-6 until a cognition-preserving treatment hard-passes its frozen Gate.
