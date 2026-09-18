# Method Sampling Preregistration — gen43 window (2026-09-19)

冻结时间：2026-09-19 02:20 +08:00（采样期内规则不变；追加 session 分类须在本文档记录）

## 1. 测量锚点与解释边界

- 锚点：gen43 = `1103a7493`，svc-8b486e73 succeeded，三服务 01:44/01:45 启动。
- **解释边界（关键）**：三服务启动时主仓工作区含未提交 WIP
  `src/llm_loop/memory/extractor.py`、`src/llm_loop/methods/learning_journal.py`、
  `src/llm_loop/methods/learning_plane.py`（01:44 时的版本，live 进程载入的即此状态）。
  02:13–02:17 第三方会话仍在同路径继续开发（另触及 factory.py / test_extractor.py）。
  本窗读数 = gen43 已提交代码 + 上述 WIP 快照，**归因时不得当作纯 gen43**。
- 采样期不 restart、不动 method 路径；每新增一次 succeeded restart 即新锚点窗，需在报告注明。

## 2. 分类规则（冻结）

- **工程类 run**（排除出"正常任务"分母）：目的为改 src/tests/tools、部署/测量/审计
  evolution 的 run；含所有直接产生本测量、部署或代码改动的会话。
- **正常任务 run**：其余。
- session→类别表（追加须记录）：
  | session | 类别 | 依据 |
  |---|---|---|
  | 16a8c1d8… | 工程 | 本测量/部署会话 |
  | 8264c548… | 工程 | 采样执行（gen33 期曾为正常任务，gen43 窗内按工程计） |
  | 02:13–02:17 改 methods/memory 的第三方会话（id 待收尾回填） | 工程 | 直接改 src |
  | cf2dc391 / afa4ba80 / 7d43084f | 待定 | 收尾后按目的归类 |

## 3. T4 预注册决策标准（非工程 run ≥ 20 时触发，仅一次判定）

设：发现率 = 有 kind=method 搜索的正常 run 占比；记账率 = usage.jsonl 新增条目对应正常 run 占比。

1. 发现率 = 0 → 问题在"想起来搜"，触发 P2 检索入口改动设计（不改语义）。
2. 发现率 > 0 且记账率 = 0 → 问题在声明成本，分析 record_use 摩擦（入口/参数/时机）。
3. 发现率 > 0 且记账率 > 0 → 看 applied/adapted/not_applicable/rejected 分布，
   再决定 qualification 设计；不自动晋级。
4. 非工程 run < 20 → 不做任何 P2 决策，只续采。

## 4. 执行计划

- 中午 ~12:00 一次性中间读数（wake 已挂）：`python3 tools/measure_method_sampling.py --from-gen 43`。
- 傍晚 T3 终读：同命令 + 分类表归并，产出正式报告。
- 脚本两个已知坑（已写入其 docstring）：EventStore 平铺/分片双形态；原始参数仅存于
  assistant message.appended tool_calls（tool.execution.* 只有 args_sha256）。
