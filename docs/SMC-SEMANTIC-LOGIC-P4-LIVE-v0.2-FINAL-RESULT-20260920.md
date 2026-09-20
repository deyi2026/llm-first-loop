# SMC P4-LIVE ActionRef v0.2 — Final LIVE Qualification Result

> Date: 2026-09-20
> Base PRE-LIVE result: `5849992e7dc39dad0409337e54b29956b61aba78`
> Protocol commit: `267ad5778be2af324e38ba8422a5d1a29bbe053d`
> Result: **QUALIFIED**
> Deployment / merge: **NOT AUTHORIZED / NOT PERFORMED**

## 1. Final adjudication

The frozen P4-LIVE v0.2 matrix completed in exact serial order `V02-L01` through `V02-L20` with **20/20 PASS**. No row was retried, substituted, reordered, or widened. The run used the frozen exact 12-tool canary scope and one local Ornith server on port 8901 with prompt/decode concurrency 1.

The prior v0.1 NOT_QUALIFIED result remains immutable. v0.2 is a new qualification run after the independently qualified R12 target-identity production fix; it does not reinterpret or overwrite the old L02 result.

## 2. Success rows V02-L01..L05

All five typed ActionRef mutation paths passed against a real isolated Browser fixture:

- `V02-L01` navigate;
- `V02-L02` click;
- `V02-L03` fill;
- `V02-L04` select;
- `V02-L05` scroll.

Each row made exactly one Ornith request, produced exactly one expected typed tool declaration, resolved the issued ActionRef through the production resolver and immutable execution bridge, carried the hidden GroundingRef / inner action id / exact Browser target provenance, produced exactly one intended Browser dispatch, persisted `running -> ok` Browser receipts and the outer WAL receipt, and produced the expected physical effect. No automatic retry occurred.

`V02-L02` is the direct positive regression proof for R12: the old v0.1 `browser_target_precondition_mismatch` did not recur; exact target binding succeeded and the click effect occurred exactly once.

Across the five success rows: **5 model requests**, **12,730 prompt tokens**, **559 completion tokens**.

## 3. Rejection rows V02-L06..L16

`V02-L06` through `V02-L15` all failed closed before candidate Browser dispatch under their frozen invalidity condition:

- cross-session;
- cross-workspace;
- prior run generation;
- expired binding;
- Browser runtime restart;
- wrong target kind;
- ActionRef integrity corruption;
- stale document/navigation generation;
- Browser target replacement before first mutation use;
- effect binding absent / revoked.

For these ten candidate rows: **model requests = 0, candidate dispatches = 0, candidate click effects = 0**. `V02-L13` uses one explicit fixture setup navigation only to create the stale-document condition; it is not a candidate mutation dispatch.

`V02-L16` proves at-most-once behavior: the first exact click succeeds once; the second exact declaration is rejected as `duplicate_action_id`. Total dispatches remain 1 and total click effects remain 1.

## 4. Crash / ambiguity rows V02-L17..L20

All four recovery rows passed with zero automatic replay:

- `V02-L17`: durable ActionRef execution bridge exists but Browser `running` receipt does not; recovery state is `prepared_before_browser_running`, executed=false, dispatch=0.
- `V02-L18`: Browser `running` receipt exists without a terminal receipt; recovery state is `browser_running_outcome_unknown`, dispatch=0, no replay.
- `V02-L19`: Browser terminal `ok` receipt exists while outer `ToolExecutionJournal.finished` is missing; recovery is `browser_terminal_exact`, reconstructs the exact success receipt, and does not dispatch again.
- `V02-L20`: transport loss occurs after a possible physical effect; terminal evidence remains `running -> failed` with `dispatch_outcome_ambiguous`, `automatic_retry_performed=false`, the outer receipt is durable, and later recovery performs no replay.

## 5. Machine aggregation and evidence

`MATRIX-RESULT.json` independently re-reads all twenty row artifacts, checks their exact manifest order and hard-gate invariants, and reports:

- status: `QUALIFIED`;
- row count: 20;
- all rows pass: true;
- total model requests: 5;
- total candidate dispatches: 8;
- automatic row retries: 0;
- automatic replays: 0.

The eight candidate dispatches are fully accounted for: five success rows, the first half of duplicate row L16, L19's single successful mutation before outer-finished loss, and L20's single possible-effect dispatch before transport loss. No additional dispatch is inferred or hidden.

All row artifacts are individually SHA-256 pinned inside `MATRIX-RESULT.json` and `FINAL-VALIDATION.json`.

## 6. Post-LIVE qualification gates

After the LIVE matrix, no LIVE row was run again. The current descendant / adjacent deterministic selection plus v0.2 protocol tests passed **177/177**. Ruff passed. Pyright reports **0 errors / 0 warnings**. The result validator recheck passed. There is **zero production `src/` delta** relative to the frozen PRE-LIVE result.

Repository-wide `ci_gate.sh` remains red only on the inherited baseline set: candidate=72 failures and PRE-LIVE base=72 failures, `candidate_only=0`, `base_only=0`, with identical failure-set SHA-256 `67cb4e57ea0f23572c7e4d91ee576468da0502f183b7bf6e6ccb92fc10583412`. This is **baseline-equivalent red / no new failure**, not a claim that full CI is globally green.

## 7. Governance boundary

This qualification did not patch production code during LIVE execution and did not deploy, restart Web/Feishu/8901, open or merge a PR, or modify `main`.

The next mandatory boundary is **before any deploy or merge**. Promotion requires a separate explicit authorization after the exact result is remotely frozen and the protected refs are independently verified unchanged.
