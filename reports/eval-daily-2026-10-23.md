# LFL 评测日报 2026-10-23

> 口径：`eval/rules/statistics.md`（Wilson 95% CI；样本不足只给方向性结论；负结果同等呈现）。
> 数据源：`data/audit/action_trace.jsonl`（动作）、`data/audit/exception_log.jsonl`（异常）、`data/audit/guarded_requests.jsonl`（成本与缓存）、`data/archives/`（压缩档案）。

## 指标

| 指标 | 值 | 样本 | 口径说明 |
|---|---|---|---|
| 首试成功率 | 1.000 | n=282 | 按任务键取首次尝试的占比；样本不足时仅方向性 |
| 停滞次数 | 4 | — | action_trace/exception_log 中停滞事件计数 |
| 异常率 | 0.079 | calls=5141, exc=444 | exception_log /（工具调用 + 异常） |
| 压缩后存续率 | 数据不足 | archives=266, recovered=None | 压缩档案数可数（archives/*.jsonl），但**运行时无取回留痕** → 存续率无法算出（数据缺口，见 P5 待办） |
| 成本（token in/hit/out） | 292406992 / 273559995 / 0 | llm_calls=3671 | guarded_requests 当日聚合 |
| 缓存命中率 | 0.936 | tokens_hit / tokens_in | prompt cache 命中占比（LFL 关键指标） |

## 数据缺口（如实登记，不以 proxy 冒充）

- **压缩后存续率无法计算**：压缩档案数可数（`data/archives/*.jsonl`），但运行时**不对「取回」留痕**（archives/ 下无 recovered 标记，audit 流里也无取回事件）→ 需要在压缩档案读取路径补一条留痕后才能计算。待办见 P5。
- **tokens_out 恒为 0**：`guarded_requests.jsonl` 只记 `tokens_in`/`tokens_hit`，不记输出 token → 输出侧成本暂不可见。

## 读取计数

- action_trace: 18523
- exception_log: 444
- declaration_check: 24
