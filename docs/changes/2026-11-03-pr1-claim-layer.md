# PR-1 claim 层落地记录（2026-11-03）

对应设计：`docs/design/DESIGN-20261103-multi-task-concurrency-v2.md` §11.1.1 / §14。

## 交付物

| 文件 | 作用 |
|---|---|
| `src/llm_loop/introspection/task_claim.py` | claim 模型 + 每 goal append-only 账本 + fencing 校验 + 组合入口 |
| `src/llm_loop/introspection/task_store.py` | `safe_goal_id()` 单点归一；`update(emit_event=)`；`update_with_claim()` |
| `src/llm_loop/introspection/tools_task.py` | `claim_task` / `renew_task` / `release_task`；`task_update` 支持 `claim_token` |
| `src/llm_loop/introspection/registry_task.py` | 三个新工具的分派 |
| `src/llm_loop/subagent/runner.py` | per-parent fanout 闸 + `_ReserveDenied`（计数/上限/出口） |
| `src/llm_loop/config.py` | `claim_*` 与 `max_running_children` 配置项 |
| `scripts/claim_metrics.py` | 五指标 + 账本交叉计数 + `--since` |

## 验证回执（实测）

- `tests/test_task_claim.py` 31 passed
- `tests/test_task_claim_tools.py` 3 passed
- `tests/test_claim_metrics.py` 3 passed
- `tests/unit/test_claims_events*.py` 15 passed
- 分批定向回归（task/goal/subagent/config/registry 相关文件）通过
- `ruff check` 改动文件 0 新错（仓库基线 16 条在 feishu/browser 等既有文件）

## 未验证（不得当作已验证）

- 全量测试未跑（RULE-AI-28 需独立审查 PASS 后执行）
- 观察期真实数据为空：见 `2026-11-03-pr1-claim-metrics-baseline.json`（分母为 0，所有比率为 null）
- `enforce` 模式未接（PR-2）
