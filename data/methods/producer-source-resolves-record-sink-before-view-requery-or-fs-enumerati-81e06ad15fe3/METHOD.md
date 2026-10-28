---
method_id: producer-source-resolves-record-sink-before-view-requery-or-fs-enumerati-81e06ad15fe3
name: producer-source-resolves-record-sink-before-view-requery-or-fs-enumeration
description: 持有 ID 型记录需要完整原文与权威状态，而 search/evidence 视图反复只给同一段截断文本时，不要换措辞重查、也不要全库枚举文件位置：先从回执 provenance 抽取 producer 工具名，grep 其源码读出持久化 sink 路径与目录解析逻辑，直接读 sink 中该 ID 的条目取全文与状态。用一次 evidence hydration 区分『视图截断』与『源头截断』：若存储块在采集时即截断（complete:true 但内容不完整），任何视图重读都无效，必须跳到 producer sink。多数据根时按 producer 解析逻辑（env/cwd）定权威根，或先读仓库内已命名的同域 experience。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:e3d65611-a839-42fc-bf6f-fae957ddf6cf:1035:0891e49ac9493a6ee7eb
evidence_refs: learning:learn:e27b77c46af6
created_at: 2026-10-15T07:00:16.588073+08:00
updated_at: 2026-10-15T07:00:16.588073+08:00
---
## Trigger
任务持有不透明记录 ID（审批单/演进建议/工单），需要其完整原文或当前权威状态；同一 ID 的检索命中反复返回同一段截断文本，或回执 provenance 已标明 producer 工具但未给出落盘位置。

## Discriminator
两个当时即可见的事实：(1) 同一 ID 的检索命中重复出现同一段截断文本——继续换措辞检索无信息增益；(2) evidence hydration 的 range/integrity 元数据显示 complete:true 但内容在采集时即被截断——缺口在源头而非视图。任一成立即排除『再查一次』，把下一步缩为『定位 producer 的持久化 sink』。

## Short path
- 按 ID 检索一次，从回执 provenance 抽取 producer 工具名与记录 kind（未知量：谁生产并持久化这条记录）
- grep 代码库中 producer 名，读其存储类的 sink 路径表达式与目录解析逻辑（未知量：权威全文落在哪个文件、哪个根）
- 若目录列表已出现同域命名 experience（如 store 数据根歧义、状态流转路径差异），先读它再选根（未知量：多根环境下哪个是权威）
- 直接解析 sink 文件中该 ID 的条目，取完整原文与状态字段（未知量：提案全文 + 当前状态）
- 全文与状态齐备即按原文执行，走与状态匹配的完成路径；不再回视图层重复检索

## Stop conditions
- sink 条目给出完整原文（含视图缺失的中段）且状态字段与人工回执一致
- producer 无本地落盘（纯远端服务/黑盒）——停止文件定位，改用服务端读取/状态工具

## Verification
- sink 条目 ID、状态、时间戳与人工回执一致
- 全文结构完整，覆盖截断视图缺失的中段（问题/方案/验收标准齐备）
- 执行后按 producer 定义的状态机收口（如 accepted 态走 CLI 而非仅受理 executing 的工具），核对 verified_at 已落盘

## Counterexamples
- 视图已 complete 且包含全部所需内容——直接执行，无需追 sink
- producer 是外部服务或 vendored 黑盒，无源码可读——应走服务端 API/状态工具，读源码定位 sink 不可行
- 记录仅存在于会话内存、尚未落盘——sink 不存在，只能依赖回执与检索
- 并发多写者下 sink 本身可能滞后——终局断言前仍需成稿时重读权威记录（另一方法覆盖），本方法只解决『去哪读全文』
