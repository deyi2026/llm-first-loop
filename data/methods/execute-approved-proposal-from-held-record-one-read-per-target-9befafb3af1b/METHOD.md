---
method_id: execute-approved-proposal-from-held-record-one-read-per-target-9befafb3af1b
name: execute-approved-proposal-from-held-record-one-read-per-target
description: 人工回执要求「核实 evolution 状态后继续执行」时，已取回的提案记录本身就是执行计划：它点名交付目标（SoT 文件、相邻规则定位、需登记的台账/治理指针）。状态经一次权威读取确认后，执行准备阶段的每次工具调用都应解析工单点名的未知量；已返回的记录与搜索命中（精确路径、标题行号）就是已固定的获取通道。同一事实不得换更宽通道重复获取：全文读后再分段重读同一文件、用记录 ID 做 filename glob（必然落空）、路径已知时全库 grep（只剩超时风险）。与 resume-continuation-via-named-provenance 的边界：本卡管「工单在手、目标已点名」的执行阶段防重复获取，不管无活动 goal 的续跑状态重建。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0e1e3567-343d-44ae-b119-9a2d6a9ee4c5:215:0008616d19f36f395693
evidence_refs: learning:learn:accbccf58d5c
created_at: 2026-10-13T03:47:04.400841+08:00
updated_at: 2026-10-13T03:47:04.400841+08:00
---
## Trigger
外部审批回执要求核实某记录型状态后继续执行已批准提案；该提案记录已按精确 ID 经 search_records 取回且可见文本已点名目标文件与相邻规则；随后进入执行准备阶段（读取目标正文、取登记格式、定位台账）。

## Discriminator
当时已见的三个事实：①提案记录正文已点名 SoT 目标与相邻规则（邻规则「仅管用前」、末条规则编号、目标文件名）；②内容搜索命中已给出精确路径与标题行号（如 ai_rules.md:444 与三个审查闸 skill 路径）；③event_stream 已确认 executing。此时每个所需事实都有已固定的来源，重复获取不缩小任何未知量——记录正文只存在于记录库（文件名 glob 记录 ID 无解，本集实测无匹配），精确路径已知时全库 grep 只剩超时风险（本集实测超时后自己改用精确路径）。

## Short path
- 未知量：提案是否已批准可执行？→ 一次权威读取（event_stream/记录状态字段）确认 executing 即停，不换工具重复核实。
- 未知量：要改哪些载体？→ 直接从已取回的提案记录列清单（SoT 目标文件与节、相邻规则正文、需补登的台账、治理指针），不重新搜索提案本身。
- 未知量：各目标当前长什么样？→ 按已命中路径/行号对每个点名目标做单次范围读取；需要记录完整正文时按 kind+ID 走记录通道水合，不做文件名搜索；台账等未给路径的载体允许一次内容搜索定位后立即收窄。
- 执行编辑 → 强制代码审查闸（独立子代理初审+窄复审+回执）→ 定向回归 → 如实报告（预存失败对照干净基线抽样标注）。每次读取前自检：该事实本任务是否已返回过？已返回则复用，跳过该调用。

## Stop conditions
- 状态已被一次权威回执确认；不追加任何重复核实调用
- 工单点名交付物已逐个完成一次读取并进入编辑；无针对已返回内容的重复调用
- 记录正文需求已由记录通道满足；全程未出现记录 ID 的文件名搜索或全库宽 grep

## Verification
- 逐条映射 post-verification 的每次读取 ↔ 工单点名未知量，要求 1:1；映射外的读取必须说明新未知量，否则取消
- 同一 artifact 本任务读取次数 ≤1（连续不重叠的分页不算重复）；搜索调用不以已取回记录的 ID 作为文件名或全库模式
- 工具失败（如 grep 超时）后的替代调用必须用已点名精确路径，不得换成同义宽枚举变体

## Counterexamples
- 提案记录取回即截断且无恢复句柄、按 ID 水合失败：允许对记录库做一次定向再检索（仍不做文件系统 glob）
- 工单只说「更新台账」但未给路径：允许一次内容搜索定位，命中后立即收窄到该文件，不再扩大
- 任务本身是全文审计/SoT 同步锚点核查（锚点遍布全文件）：单次全文读取就是正确单位，不强行改分段
- 需输出终局断言且资源有已知并发写者：成稿时点 fresh read 属 fresh-read-authoritative-record-before-finality-claim 管辖，不适用也不冲突
- 裸「继续」且无活动 goal 的续跑状态重建：走 resume-continuation-via-named-provenance-and-git-delta，不用本卡
