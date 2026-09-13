# Browser Semantic Execute A/B Protocol v0.3

## Question

在同一 LFL Browser Phase 1 runtime、同一 Ornith、本地 8901 串行配置与同一真实 loopback 页面任务下，把模型面从“手工填写完整 `SemanticAction`”替换为“`browser_semantic_execute(verb,target_ref,args)`，机械编译封装在工具内部且工具描述直接说明用法”，是否能够形成可用的真实 Browser 操作路径？

本实验**不测 Method 检索/水合**。用户裁决已经明确：执行程序属于工具内部，工具自己描述用法。因此两臂都不暴露 `search_records`；`browser_perceive` 与 `get_tool_schema` 保持完全相同，唯一产品级干预是 mutation interface package。

## Arms

- `full_action`: `browser_perceive + browser_action + get_tool_schema`
- `semantic_execute`: `browser_perceive + browser_semantic_execute + get_tool_schema`

`browser_perceive` 在两臂使用同一中性 B-QUAL 只读描述，避免 treatment 从感知工具获得额外提示。控制臂 `browser_action` 使用已资格化 full SemanticAction 合同。Treatment 使用生产 `browser_semantic_execute` 的真实 compact/full contract，不为实验改写。

## Model/runtime freeze

- model: `cognilocal/ornith-1.5-35b-a3b-mlx`
- Thinking ON / reasoning effort medium
- temperature 0 / top_p 1 / top_k 0 / min_p 0
- max input 184000 / max output 16000
- max iterations 12
- no model fallback
- lazy tool schema ON
- fresh session, DATA_DIR, Chrome profile and fixture for every row
- exact isolated Chrome target; `--use-mock-keychain --password-store=basic`
- serial rows only; 8901 must have exactly one MLX server with prompt/decode concurrency = 1

## Frozen paired smoke

Three task pairs, one run per arm per task = 6 rows total. Arm order inside each pair is seeded by `2026091306`.

1. `click_commit`: navigate, click exact object once, verify submitted state.
2. `fill_submit`: navigate, fill exact value, click save, verify external saved value.
3. `delayed_wait`: navigate, wait until Ready, click only after enabled, verify no early click.

Task success comes only from the loopback fixture's external-state oracle. Tool success or ActionReceipt `ok` is never task success.

## Expansion gate for this smoke

The 6-row smoke passes when all are true:

- 6/6 rows are mechanically complete (no infra fail/timeout/invalid surface);
- exact intended provider surface in all rows; no fallback; no SecurityAgent spawn;
- SMC mutation adopted in at least 2/3 rows in **each** arm;
- semantic_execute arm passes at least 2/3 external task oracles;
- semantic_execute produces at least one object `ok` receipt and at least two navigate `ok` receipts;
- semantic_execute has zero old scope/version blocker receipts (`expected_version_unavailable`, `resource_scope_mismatch`, `version_scope_mismatch`, different-snapshot blocker);
- automatic retry remains zero across both arms.

Control-vs-treatment improvement is **not** itself a gate. Paired deltas are reported as directional evidence only; if both arms pass equally, the correct conclusion is “thin interface is viable but superiority is not demonstrated.”

## Non-claims

This smoke does not qualify cloud providers, Phase 2 vision/native UI, root-level scroll, general model intelligence, or statistical superiority. It does not permit automatic target selection/retry/latest/rebind/task-completion judgment.
