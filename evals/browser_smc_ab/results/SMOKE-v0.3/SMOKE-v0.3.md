# SMC Browser real-model A/B — Smoke v0.3

> **Status: STOP_EXPANSION_GATE_FAIL**

## Result

Frozen v0.3 smoke completed **6 / 6** rows on formal execution HEAD
`cec232676812fd6d8b5ad8dccb6731402272c145`, plan SHA256
`dc7aa7f4cc73cc531fd1d3fc2c1de6f4ff5fa6e4bb53c451fbee0b9a8c753dd4`.
The predeclared expansion gate failed, so the remaining 14 rows were **not run**.

- legacy task oracle: **3 / 3 PASS**
- SMC task oracle: **0 / 3 PASS**
- SMC adoption: **2 / 3** smoke rows, requirement 2
- successful SMC physical dispatch receipts: **1**, requirement 1
- frozen old-scope blocker count: **0**, requirement 0
- SMC automatic retry performed: **0**
- SMC SecurityAgent-spawned runs: **0**
- expansion: **STOP**

The gate failed for two independent reasons:

1. row 1 did not finish the worker within the frozen per-row 240 s limit, so
   execution health is not valid; and
2. no SMC task passed its external-state oracle.

The raw row-1 label is `INVALID` because the v0.3 runner checked the absent
terminal surface after it had already classified `worker_rc=null` as a timeout.
The immutable mechanical facts are `worker_rc=null`, no terminal worker payload,
and `wall_s=240.945`; this is a **per-row TIMEOUT**. The classification precedence
bug was fixed only after the smoke, in
`59429e757bf78af46464639be8409bc2ee64976e`, and the formal raw row was not
rewritten or rerun.

## Paired directional facts

| Task | SMC | Legacy | SMC−legacy input tokens | SMC−legacy tool calls | SMC−legacy rounds |
|---|---|---|---:|---:|---:|
| `click_commit` | TIMEOUT* | PASS | N/A | N/A | N/A |
| `fill_submit` | FAIL | PASS | +51,324 | +4 | +3 |
| `delayed_wait` | FAIL | PASS | +63,625 | +6 | +5 |

`*` Raw v0.3 label is `INVALID`; see the timeout-classification note above.

For the two terminal SMC runs, median input was **77,548.5 tokens**, median
rounds **12**, and median tool calls **12**. Legacy median input was **13,289
tokens**, median rounds **7**, and median tool calls **6**. These are descriptive
paired smoke facts only; they are not a statistical claim, and cache/token
comparisons remain confounded by arm-specific tool-schema prefixes.

## What the mutation-scope correction actually fixed

The previous v0.1 smoke stopped before any successful SMC Browser mutation: all
three SMC tasks independently selected the then-permitted `snapshot` mutation
scope and hit the strict same-generation/different-snapshot stale rule.

That specific conflict is no longer present in v0.3:

- model-facing mutation scope is now `object` for object verbs and `resource`
  for navigation;
- the frozen old-scope blocker counter is **0**;
- `fill_submit/SMC` produced one terminal `ok` ActionReceipt for a real
  `navigate` dispatch;
- no automatic retry or silent replay was used to obtain that receipt.

Therefore the correction restored a physically executable path. It would be
incorrect to retain the old conclusion that Phase 1 mutation is mechanically
unable to dispatch.

## New blocker exposed by the smoke

Restoring dispatch did **not** make the model-facing action contract usable
enough for these tasks. Across terminal SMC receipts the rejection reasons were:

| Mechanical reason | Count |
|---|---:|
| `version_precondition_indeterminate:expected_version_unavailable` | 3 |
| `version_precondition_indeterminate:resource_scope_mismatch` | 2 |
| `args_contract_mismatch` | 1 |

The single successful receipt was `navigate`; the two execution-valid SMC runs
never reached an `ok` object mutation such as `fill` or `click`. Their model
trajectories consumed the full 12-round budget while repeatedly navigating,
perceiving, waiting, and attempting to reconstruct action/version fields.

This distinction matters: `smc_scope_blocker_count=0` is only the frozen counter
for the **old snapshot-scope blocker**. It does not mean the version-grounding
path is healthy. The observed `resource_scope_mismatch` and
`expected_version_unavailable` receipts are new mechanical evidence and are
reported separately rather than hidden behind the old metric.

The treatment surfaces also differ materially in shape: the frozen SMC lazy
surface is 2,849 JSON characters, while the legacy surface is 807. This is a
context fact, not by itself a causal attribution.

## Legacy result and caveat

Legacy passed all three external-state oracles, but its traces were not
frictionless: `fill_submit` had four raw tool failures before completion, and
`delayed_wait` included an internal Playwright tool timeout before later
recovery. The smoke therefore supports a directional usability difference in
this fixture set, not a claim that the legacy surface is generally safer or
better engineered.

## Decision

Do **not** run the remaining 14 v0.3 rows. Do not weaken stale checking, remove
the mandatory fresh pre-dispatch observation, add silent retry, substitute a
different target, or reinterpret a rejected ActionReceipt as success.

The next recommended work is a separate **model-facing Browser Action ergonomics
contract** phase, while keeping the internal canonical SemanticAction and all
existing safety boundaries. The design should test whether purely mechanical
fields can be removed from model authorship, for example:

1. derive frozen fields such as schema/domain/operation class/idempotency class/
   atomicity/version-precondition inside the tool wrapper;
2. derive the now-unique verb→version-scope mapping mechanically rather than ask
   the model to restate it;
3. let the model select an observation/grounding reference and semantic target,
   then derive `expected_version` and `scope_ref` from that chosen evidence;
4. preserve exact Semantic-ID re-resolution, pre-dispatch fresh capture,
   stale/indeterminate rejection, append-only receipts, and no replay.

Any such change requires deterministic + live requalification and a **new** A/B
protocol identity. v0.3 must remain a closed STOP result. Phase 2 vision/native
UI and root-level scroll remain out of scope.

## Evidence

- `execution-manifest.json` — exact formal git/model/provider/Playwright/surface/source facts
- `runs.jsonl` — six privacy-safe mechanical run records
- `smoke-gate.json` — frozen expansion gate result
- `analysis.json` — offline paired mechanical scorer
- `SMOKE-v0.3.json` — closeout decision, classification note, and blocker facts

Evidence SHA256:

- `runs.jsonl`: `ec6d9c1f3041105e6a19f461532e7c502cdaf19066edeee5ddf9dc5a92eab6de`
- `execution-manifest.json`: `e602f07b3ea82493ddead43a1d2a302e000da8c0e2895ca496a423879fad8f2f`
- `smoke-gate.json`: `3de775ebec7c384a3c214cc12844b3e847628666a46e496cfa90066df8668b18`
- `analysis.json`: `66aee593d57f65cb159d5199f55b989e25f5621f9abccc7b63cb08f434855db6`

The public result bundle contains no prompt body, Playwright source code,
absolute user path, credential, model private reasoning, Chrome profile, or LFL
session store. Full uncurated browser/profile evidence is retained outside the
public repository.
