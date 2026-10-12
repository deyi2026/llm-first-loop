# SMC Browser real-model A/B protocol v0.3

Status: **frozen_not_executed** until committed-state preflight passes.

v0.3 is an execution-controller re-freeze of v0.2. The v0.2 execution was invalidated because a single outer controller window attempted the whole six-row smoke and terminated during row 6. `EXECUTION.v0.2.INVALID.{md,json}` preserves that decision. No v0.2 result is pooled into v0.3.

The causal design is unchanged from v0.2: corrected SMC Browser Phase 1 versus legacy Playwright, same five deterministic loopback tasks, same external-state judges, same exact three-tool arm surfaces, same Ornith/provider contract, same fresh session/DATA_DIR/browser-profile/action-id isolation, and the same smoke expansion gate.

## Execution identity

- schema: `smc.browser_real_model_ab.v0.3`
- seed: `2026091303`
- 20 paired rows (5 tasks × 2 arms × 2 repeats)
- first three pair blocks remain the six-row smoke: click, fill, delayed-wait
- formal runner invocations use `--max-new-rows 1`

`max_new_rows_per_invocation` is part of the execution manifest. Each invocation recomputes and exact-compares git HEAD, source hashes, provider contract, 8901 identity/config, Playwright facts, tool-surface hashes, plan SHA, and this controller bound before running a new row. This prevents an outer orchestration timeout from silently killing a later row after earlier rows consumed the same command budget.

## Smoke expansion gate

Unchanged from v0.2: 6/6 complete and infrastructure-valid; no fallback; exact surfaces; SMC adoption >=2/3; legacy physical adoption >=2/3; SMC terminal `ok` dispatch >=1; SMC mutation scope blocker count=0; SMC task oracle PASS >=1/3. Any failed gate stops the remaining 14 rows without runtime/prompt/task tuning.

## Interpretation boundary

v0.2 diagnostic rows may explain why v0.3 exists but are not statistical samples. v0.3 starts from a new cold 8901 process and fresh benchmark workdir after committed source freeze. Token/cache metrics remain descriptive; binary success, duplicate side effects, safety rejections, ActionReceipt status, retry facts, rounds/tools and latency remain separate facts.
