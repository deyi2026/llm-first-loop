---
method_id: split-compound-id-queries-on-zero-hit-after-proven-existence-3bb2b9093422
name: split-compound-id-queries-on-zero-hit-after-proven-existence
description: 第一方记录/事件检索工具对『多个标识符或多个空格分隔关键词』的复合查询返回零命中，而此前一次查询已在同一 store 命中过目标记录时，零命中的失败变量是查询串的 token 组合（此类工具多按整串/子串匹配），不是记录不存在。正确动作：停止同义词变体、多 ID 拼接与全量事件流枚举，按每个 ID 一条单 token 查询逐个取状态字段。与 verify-external-state-change-via-registry-record-by-id 的边界：那张卡决定『去哪查』（按 ID 查权威登记簿），本卡决定『复合查询零命中时如何归因与拆分』，两者可叠加。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a33fbd45-6151-492f-b5eb-5fc45e989f08:1146:7ec9af39f8be625daa97
evidence_refs: learning:learn:2f7ad532acb1
created_at: 2026-10-21T19:10:01.238532+08:00
updated_at: 2026-10-21T19:10:01.238532+08:00
---
## Trigger
检索/事件流工具收到一条含 ≥2 个精确标识符或多个空格分隔关键词的查询并返回零命中；且同一 store 此前一次（类型限定）查询已命中过目标记录，存在性已证；待解未知量是逐条记录的状态字段

## Discriminator
存在性已被先前命中证明 + 复合查询零命中 ⇒ 唯一被隔离出的失败变量是查询串的多 token 组合；本集同工具内对照可观察：event_stream 四词复合查询零命中，改单 ID 查询即命中（同 store、同目标，仅 token 数不同）

## Short path
- 类型限定查询（如 kind=evolution）证明记录在库并取正文；未知量：记录是否存在、建议内容
- 需逐条状态时，按回执给出的每个 ID 各发一条单 token 查询；未知量：该 ID 的状态字段
- 任一复合查询零命中且存在性已证 → 不换同义词、不拼多 ID、不拉全量流，立即拆为单 ID 查询
- 逐条核对单 ID 回执状态与外部声明一致；全部一致即核实闭合，停止查询进入执行

## Stop conditions
- 每个 ID 均取得含状态字段的权威回执，且与外部回执声明一致
- 单 ID 查询仍零命中：存在性假设被推翻，此时才扩大到其他通道/工具交叉验证

## Verification
- 拆分后命中条数不少于先前证明存在的记录数（N 个 ID 应 ≥N 条命中）
- 逐 ID 回执中的状态值与回执/工单声明逐一对照一致后才宣告核实完成

## Counterexamples
- 检索面支持分词/布尔/语义匹配（grep 多模式、向量检索等）时，复合查询零命中更可能是真不存在：应先做类型限定列举证明存在性，拆词无益
- 存在性未经任何先前命中证明时，复合零命中无法归因于查询格式，第一步是窄列举而非拆词
- ID 是常见短串、单查会命中大量无关记录时，须保留 kind/scope 过滤条件，只拆 ID 不加过滤会引入新噪声
