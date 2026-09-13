# SMC Browser Semantic Execute Confirmatory v0.5 — Result — 2026-09-13

## 裁决

**Confirmatory Gate：FAIL。**

正式状态：

- 本地 `browser_semantic_execute`：**能力已证明，但重复稳定性 NOT_QUALIFIED**；
- 默认启用：**NOT_QUALIFIED**；
- GLM / MiniMax / DeepSeek cloud canary：**NOT_RUN_BY_GATE**。

这次失败不能归因于 legacy `full_action`：它完全没有进入本轮模型 surface、infra validity 或 gate。6 行全部由同一 semantic treatment 独立运行。

## 冻结身份

- protocol commit：`5b1c7fef84bfc77cc31f67ab2d1f5edbfb0a4e16`
- frozen plan SHA256：`490c1e2cd1b9377468eb07dc06d05b8950faf10db4b61748ff89af1005b8f878`
- provider surface SHA256：`a15462bafcbd1b54ab917a8c8638671c6028006c914ef264664fd921883ee6d1`
- treatment surface 与 v0.4 实测 semantic surface **完全相同**；本阶段生产/runtime/tool 文案 **零改动**。

运行仍固定为同一 Ornith、Thinking ON、184K input / 16K output、temperature 0、max_iterations=12、240s worker timeout、fresh session/data/Chrome profile、严格串行、无 model fallback。

## 预注册 Gate 结果

| 条件 | 结果 |
|---|---:|
| 机械完整 rows | 6/6 PASS |
| infra valid | PASS |
| surface exact | PASS |
| no fallback / no SecurityAgent | PASS |
| SMC adoption | 6/6 PASS |
| external task oracle | **3/6 FAIL** |
| click_commit repeats | 1/2 |
| fill_submit repeats | 1/2 |
| delayed_wait repeats | 1/2 |
| every-row required navigate/object receipts | **FAIL** |
| old scope/version blockers | 0（要求 0） |
| automatic retry | 0（要求 0） |

关键事实是：**三个任务都恰好 1/2 PASS。** v0.4 的 3/3 是有效方向性正证据，但在独立 repeat qualification 下没有复现为稳定的 2/2。

## 六条真实结果

| Row | Task | Repeat | Result | Rounds | Tools | Navigate ok | Object ok | bad target_ref | wait failures |
|---:|---|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | `click_commit` | 1 | PASS | 11 | 10 | 1 | 1 | 1 | 1 |
| 2 | `fill_submit` | 1 | FAIL | 12 | 13 | 1 | 1 | 1 | 2 |
| 3 | `delayed_wait` | 1 | PASS | 10 | 9 | 1 | 1 | 1 | 0 |
| 4 | `delayed_wait` | 2 | FAIL | 12 | 12 | 1 | 0 | 1 | 3 |
| 5 | `fill_submit` | 2 | PASS | 9 | 8 | 1 | 2 | 1 | 0 |
| 6 | `click_commit` | 2 | FAIL | 12 | 12 | 1 | 0 | 1 | 1 |

## 失败边界

机械执行层没有回到旧问题：6/6 行都有真实 navigate `ok`，old scope/version blocker 总计 **0**，automatic retry **0**。三条失败都不是 stale/version 编译阻断。

失败发生在**轨迹预算耗尽之前没有完成最后 object 动作**：

- `fill_submit/r1`：真实 navigate + fill 已完成，但 12 rounds 用尽前没有 Save click；
- `delayed_wait/r2`：真实 navigate 已完成，但多次 wait contract failure 消耗轮次，未到 Finalize click；
- `click_commit/r2`：真实 navigate 已完成，仍在 hydrate/wait/snapshot 轨迹中耗尽 12 rounds，未到 Commit click。

成功与失败行的描述性差异也很集中：

- 成功行平均 rounds：**10.0**；失败行：**12.0**（三条失败均为 12）；
- 成功行平均 tools：**9.0**；失败行：**12.333**；
- 成功行 wait contract failures 合计 **1**；失败行合计 **6**。

这只是 6 行上的关联证据，**不能宣称 wait failure 单独因果决定任务失败**。但它与 max-round exhaustion 的共同出现足以说明下一步应继续研究模型首调/轨迹纪律，而不是改回程序语义路由。

## 仍未解决的 FCR 缺口

1. **invalid `target_ref` 仍是 6/6**：每一行都至少一次在没有可用 exact GroundingRef 前调用 semantic execute。工具正确 fail-closed，没有 dispatch。
2. **wait contract 仍不稳定**：6 行累计 7 次失败，其中失败任务占 6 次。
3. **额外 snapshot/hydrate/wait 消耗轮次**：薄执行器消除了手工 scope/version 字段错误，但模型仍会把有限的 12 rounds 消耗在不必要或不完整的 perception 调用上。

## 与 v0.4 的关系

v0.4 treatment 3/3 PASS 证明“薄 semantic executor + 局部 FCR”能真实完成 click/fill/delayed 三类任务；本 confirmatory 3/6 则证明**当前成功尚不稳定**。两轮 surface SHA 完全一致，因此不能把差异解释为 treatment 漂移。

正确裁决不是撤销 semantic executor，也不是放宽 gate，而是：**保留该架构，暂不默认启用，暂不开 cloud canary，下一阶段只读研究为什么模型稳定忽略先 snapshot / wait closed contract，并寻找比继续堆 universal prompt 更局部、更机械、可泛化的首调接口设计。**

明确不采用：自动 target selection、自动 latest/snapshot、自动 retry/replay、自动 rebind、程序侧 task completion、扩大 universal prompt、为通过 gate 重跑失败行。

## Evidence hashes

- `results.jsonl`: `916f815147faafd56faad13b044d6a254e91e7abd4f67ae041fac366e6afe0f1`
- `smoke-gate.json`: `f21c72e5f7f2fb59315fe560cdc983e87dbc6f499ace5bbd42a75065d9ba4313`
- `execution-manifest.json`: `c157ab1728678ef045794f81a0d7bbd486e98d778cc015581c72b03341953cca`
- `plan.json`: `c5be20eabb7c33ae948a1347e01b94ce7cde61f15cc8500e0e603e1426019401`
- `analysis.json`: `44529d6afd375eb5128cbbd1535ada9d839b892e949479c4a3a5592a5b0442ae`

## 非声明范围

- 本轮不是统计显著性研究；
- 不资格化任何云端 provider；
- 不证明 wait-contract failure 是唯一因果；
- 不改变 Browser Phase 1 已冻结的 stale/version/single-dispatch/receipt 安全边界。
