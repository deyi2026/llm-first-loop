# Browser Semantic Execute Treatment-Only Confirmatory Qualification v0.5

## Question

在不修改生产 Browser runtime、tool 文案、Method 或 universal prompt 的前提下，当前 `browser_semantic_execute` v0.4 产品面能否在同一 Ornith 上对既有三项真实 Browser 任务形成**可重复的确认性成功**？

legacy `full_action` 只保留为 v0.3/v0.4 历史基线，**不参与本轮 infra validity 或 gate**。

## Frozen treatment surface

唯一模型工具面：

- `browser_perceive`
- `browser_semantic_execute`
- `get_tool_schema`

必须使用 committed production lazy schema；不得在实验代码中补 prompt、改 tool description、强制 Method search、自动 target/latest/retry/rebind 或程序判完成。

## Model/runtime freeze

- model: `cognilocal/ornith-1.5-35b-a3b-mlx`
- Thinking ON / reasoning effort medium
- temperature 0 / top_p 1 / top_k 0 / min_p 0
- max input 184000 / max output 16000
- max iterations 12
- worker timeout 240s
- no model fallback
- lazy tool schema ON
- fresh session, DATA_DIR, Chrome profile and fixture for every row
- exact isolated Chrome target; mock/basic keychain flags retained
- serial rows only; one 8901 MLX server, prompt/decode concurrency=1

## Frozen confirmatory matrix

Same task prompts and external oracles as v0.4. Two fresh repeats per task, six total rows. Symmetric fixed order:

1. `click_commit` repeat 1
2. `fill_submit` repeat 1
3. `delayed_wait` repeat 1
4. `delayed_wait` repeat 2
5. `fill_submit` repeat 2
6. `click_commit` repeat 2

No row is replayed after timeout/failure. No adaptive reordering after measured execution begins.

## Pre-registered gate

PASS only if all are true:

- 6/6 rows mechanically complete: no `TIMEOUT`, `INFRA_FAIL`, or `INVALID`;
- exact intended provider surface 6/6; no fallback; no SecurityAgent spawn;
- SMC semantic mutation adopted 6/6;
- external task oracle PASS 6/6, therefore each task is 2/2 PASS;
- each row has at least one navigate `ok` receipt;
- each click/delayed row has at least one object `ok`; each fill row has at least two object `ok` receipts (fill + save click);
- old scope/version blocker receipts total 0;
- automatic retry total 0.

Observed but **not added to the gate after the fact**: invalid/non-GroundingRef `target_ref` tool failures, wait-contract failures, rejected receipts unrelated to old scope/version blockers, rounds/tools/tokens/cache/wall.

## Consequence

Only a PASS on this treatment-only confirmatory gate re-opens the next phase: minimal cloud canary using the same semantic method/interface contract on GLM / MiniMax / DeepSeek. A FAIL stays local and is reported as NOT_QUALIFIED; no gate repair or row replay is allowed.
