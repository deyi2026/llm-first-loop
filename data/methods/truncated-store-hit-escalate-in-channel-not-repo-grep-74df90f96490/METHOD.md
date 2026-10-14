---
method_id: truncated-store-hit-escalate-in-channel-not-repo-grep-74df90f96490
name: truncated-store-hit-escalate-in-channel-not-repo-grep
description: 登记簿按唯一 ID 检索命中恰好 1 条但回执截断正文/字段时，截断只是回执显示限制——完整记录已被证明存在该 store 的存储中。应同通道升级取全文：优先 store 自身的 full/分页参数；否则有界定位该 store 的账本文件（一次按记录类型过滤的 ls/glob，只列名不扫内容）后按 ID 单条读取。不要跳去全库 content 搜索 ID 字符串：本集两轮全库/全 data 扫描各超时 60s，最终三次有界调用（ls 定位 + 单文件按 ID 读）即得全量正文与 status。仅当 store 无命中、或账本文件确认为索引/存储本身截断时，才扩大到事件流或被指向的归档。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f2769b0a-b64f-4ef5-81b2-e6a1d35727de:221:a653aa2c92ce6a2e8f87
evidence_refs: learning:learn:c5227cf435f0
created_at: 2026-10-14T01:26:28.861162+08:00
updated_at: 2026-10-14T01:26:28.861162+08:00
---
## Trigger
按唯一 ID 在记录 store/登记簿检索命中恰好 1 条，但回执截断记录正文或关键字段（如 status），任务需该记录全量内容才能继续（如人工回执要求『核实状态后执行』且提案正文即执行计划）

## Discriminator
命中本身即证明完整记录存在于该 store 的存储中——截断是回执显示限制而非数据缺失，未知量是『这一条记录的全量内容』而非『这个字符串在仓库哪里出现』；若同刻已检索到的方法卡明示『路径已知时全库 grep 只剩超时风险』或目录可见大归档（archives/、zip、b64），宽 content 扫描的代价当时已可判定

## Short path
- search_records(kind=记录类型, query=ID) 命中 1 条但截断 → 把未知量收窄为『该记录全量正文与 status』，而非全仓库字符串定位
- 同通道升级：先试 store 的 full/expanded/分页参数直接重查取全文
- 参数不可用则有界定位 store 背书文件：ls/glob data/ 中与记录类型对应的账本文件（仅列目录名，不做内容匹配）
- 按 ID 从账本文件单条读出全量记录，比对 id/ts 与首次命中一致，取 status 与正文
- status 与人工回执一致 → 核实闭合；已取回记录即执行计划，进入执行，不再为同一事实换更宽通道

## Stop conditions
- 账本文件读出的 id/ts/status 与回执一致且正文完整（含结尾段落，无句中截断标记）→ 停止发现，进入执行
- store 按 ID 查询无命中，或账本文件确认只存索引/存储即截断 → 才扩大到事件流或命中指针指向的归档

## Verification
- 回读记录的 id/ts 与首次命中完全一致；status 字段与回执声明的新状态一致
- 正文含完整性标志（如提案的落地形态/排除项结尾段落），而非在句中截断

## Counterexamples
- store 命中只是引用/索引（正文存于被指向的归档会话文件）：账本文件读不到全文，应沿命中给出的指针走而非同通道升级
- 小型仓库无大归档：对唯一 ID 做全库 grep 廉价可靠，有界定位反而是多余一步
- 记录写入时即被截断（存储本身不完整）：store 读回同样截断，须回到原始提交工件（event/action trace）取全文
