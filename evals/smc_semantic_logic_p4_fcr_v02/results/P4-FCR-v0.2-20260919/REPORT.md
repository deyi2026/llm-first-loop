# SMC Semantic Logic P4-FCR v0.2 ActionRef Result — 2026-09-19

**Status: QUALIFIED — the frozen P4-FCR v0.2 hard gate passed. P4-LIVE is eligible but NOT_STARTED.**

The source-bound 40-row declaration-only A/B completed exactly once with no Browser/tool execution. Offline scoring was run only after all 40 model rows were complete.

## Frozen identity

- execution runner HEAD: `a30e864a440cf5a89851fbde1fbccc458ea1a80c`
- source-bound preflight evidence HEAD: `d6141a52e56b2d99489fd6fcbef002250fd75197`
- ActionRef implementation parent: `eae7638c83503472918927f93df49a26469200a8`
- P4-D base: `596c4175dd6cb3f0bd27656735f886b923758c80`
- raw `results.jsonl` SHA-256: `92873e536eec1f613feacecd101ec27c35111c23c23942b5cde62cd56e656df1`
- raw execution manifest SHA-256: `f6146cd79a4d59e4402316df3d2d632e9959b82ebaadc75f2e9c7f8d0995bb88`
- frozen semantic plan SHA-256: `62a4e18477d794140c46577efa32f33a4ef04da1659aa3a448499b5b74b54ad4`
- final evidence SHA-256: `7110c7c0a6305d1482a7bf92d2f5f690b3015ab538fa788b0b24c5e2e155ae5e`

The tracked manifest copy is path-sanitized because the raw source-bound manifest contains machine-private absolute filesystem paths. Its semantic content is unchanged; the exact raw manifest used by the runner is bound by the SHA above and by the earlier source-bound preflight evidence.

## Primary result

| Arm | Structural | Mechanical | No semantic call | Targeted cross-binding errors | Schema rereads |
|---|---:|---:|---:|---:|---:|
| A | 16/20 | 0/20 | 4 | 16 | 0 |
| B | **20/20** | **20/20** | **0** | **0** | **0** |

Arm B satisfies every frozen qualification requirement. All five task families are 4/4 mechanically valid under the short opaque ActionRef surface.

## Per-task Arm-B result

| Task | Structural | Mechanical | Errors |
|---|---:|---:|---|
| navigate | 4/4 | **4/4** | none |
| click | 4/4 | **4/4** | none |
| fill | 4/4 | **4/4** | none |
| select | 4/4 | **4/4** | none |
| scroll | 4/4 | **4/4** | none |

The v0.1 failure family is eliminated in the treatment arm: all four `select` repeats now declare the frozen ActionRef byte-exactly, so targeted P4-X01/P4-X02/P4-X06/P4-X07 total is **0**.

## Control-arm observation

Arm A is not part of the frozen pass threshold. In this run it was 16/20 structural and 0/20 mechanical: navigate/click/fill/scroll produced P4-X06 in all repeats, while select produced no semantic call in all four repeats. This is retained as observed control data and is not normalized, repaired, retried, or used to weaken the pre-frozen Arm-B gate.

## Safety and integrity

- rows: **40/40**
- exact plan/result sequence: **true**
- unique indices 1..40: **true**
- A/B pairing: **exact**
- provider: **cognilocal 40/40**
- truncated rows: **0**
- tool execution: **0**
- Browser runtime rows: **0**
- fallback rows: **0**
- manifest `serial_requests=true`
- manifest `normalization=false`
- manifest `retry=false`
- manifest `task_completion_judgment=false`
- no row rerun or reorder was performed

## Hard gate

| Requirement | Result |
|---|---|
| Arm B structural = 20/20 | PASS |
| Arm B mechanical = 20/20 | PASS |
| P4-X01/X02/X06/X07 total = 0 | PASS |
| tool execution = 0 | PASS |
| Browser runtime = 0 | PASS |
| fallback = 0 | PASS |
| normalization = false | PASS |
| retry = false | PASS |
| task-completion judgment = false | PASS |

## Verdict

**P4-FCR v0.2 ActionRef is QUALIFIED under the frozen FCR protocol.**

This result does not itself authorize production wiring or claim P4-LIVE qualification. P4-LIVE remains **NOT_STARTED** in this Goal, and no deployment, restart, merge, or Browser execution was performed.
