# SMC Semantic Logic P4-FCR Result — 2026-09-18

**Status: NOT_QUALIFIED — P4-FCR hard gate failed; P4-LIVE remains blocked.**

Formal 40-row declaration-only A/B completed without Browser/tool execution. The experiment itself remained mechanically valid; the treatment arm did not satisfy the frozen hard gate.

## Frozen identity

- runner/preflight anchor: `9e6e146da56c29eea3eeb8f832ade2ff2915a0d3`
- P4-D base: `596c4175dd6cb3f0bd27656735f886b923758c80`
- raw `results.jsonl` SHA256: `2c8f3561f75e7ab3a6660f47dd8b58fc37abdc2078f412bfbb3e900164204bab`
- execution manifest SHA256: `766ec577201026085d1bcaed7c7981598147a6877caf7e3ef1ae3b9d7cc388ae`
- plan semantic SHA256: `989258ba902aaf548625b043ef7649760a497697db0af28f1e53dcd687280420`

## Primary result

| Arm | Structural | Mechanical | No semantic call | Targeted errors | Schema rereads |
|---|---:|---:|---:|---:|---:|
| A | 8/20 | 0/20 | 12 | 8 | 0 |
| B | 20/20 | 16/20 | 0 | 4 | 0 |

B satisfies 20/20 structural validity, but fails the frozen requirements of 20/20 mechanical validity and zero P4-X01/X02/X06/X07 errors. Final B mechanical result is **16/20** with **4 P4-X06**.

## Per-task result

| Task | A mechanical | B mechanical | B note |
|---|---:|---:|---|
| navigate | 0/4 | 4/4 | 4/4 exact |
| click | 0/4 | 4/4 | 4/4 exact |
| fill | 0/4 | 4/4 | 4/4 exact |
| select | 0/4 | 0/4 | 4/4 structural; exact-ref mismatch in every repeat |
| scroll | 0/4 | 4/4 | 4/4 exact |

## Exact Arm-B failure family

All four B failures are `select`, one in each repeat. The expected opaque ref is:

`grounding://browser/v0.1/p4fcr-snapshot/object/el_33333333333333333333`

The model declared the same target/value each time but mechanically shortened the scheme to:

`ground://browser/v0.1/p4fcr-snapshot/object/el_33333333333333333333`

There was no fuzzy correction, normalization, retry, rebind, tool execution, or Browser dispatch; the scorer therefore correctly records `P4-X06` and leaves the row failed.

## Safety / non-effects

- rows: **40/40**, exact frozen order, no reruns
- tool execution: **0**
- Browser runtime rows: **0**
- fallback rows: **0**
- truncated rows: **0**
- provider: cognilocal on all 40 rows
- frozen manifest: `normalization=false`, `retry=false`, `task_completion_judgment=false`
- P4-LIVE: **NOT_STARTED / BLOCKED by P4-FCR hard gate**

## Comparative observation

Arm A provider surface: 8 tools / 6370 JSON chars. Arm B: 12 tools / 6943 JSON chars. B improved declaration structure dramatically (20/20 structural vs A 8/20), but the split typed surface is not smaller in total provider-wire characters in this frozen implementation and exact-ref copying remains a load-bearing failure on select.

## Verdict

**P4-FCR treatment is NOT_QUALIFIED. Do not proceed to P4-LIVE from this result.** The next design phase, if authorized, should treat the four identical `grounding://` → `ground://` select failures as a fresh protocol/design question; the completed 40-row matrix must remain immutable and must not be patched or partially rerun.
