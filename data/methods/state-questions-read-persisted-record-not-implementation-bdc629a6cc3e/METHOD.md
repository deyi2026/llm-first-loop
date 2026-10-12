---
method_id: state-questions-read-persisted-record-not-implementation-bdc629a6cc3e
name: state-questions-read-persisted-record-not-implementation
description: 当用户询问某项设置/提醒/任务『是否设置成功、还在跑、当前什么状态』，且回执或事件流已显示它由特定工具成功创建（含参数）时，答案只在该工具持久化的状态记录里（sid/周期/触发次数/wake/下次触发等字段），不在实现该机制的源码、测试或文档里。应直接定位并读取状态记录或状态查询面，按字段引用作答；只有当记录缺失、无法定位、或记录与观察行为矛盾且需机制解释时，才进入子系统源码考古。本集若走此路径可省去 3 轮面向实现细节的 search_files（含 fsync/原子写等 40+ 行无关命中）与 1 次解析失败，20 次工具调用约可减半。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:fe0e1465-7509-459e-8792-eaaf6d7269f5:0:aa570eec3332a9838ace
evidence_refs: learning:learn:aeb04728acae
created_at: 2026-10-11T21:19:10.466462+08:00
updated_at: 2026-10-11T21:19:10.466462+08:00
---
## Trigger
用户询问某个曾由工具创建的资源（定时提醒/goal/任务等）的当前状态或『是否设置成功』，且 trace/事件流中已存在该资源的成功创建回执。

## Discriminator
当时已知事实：event_stream 已显示 schedule 工具成功调用（at=08:00、max_count=60、message=执行 LFL 每日推广循环），且 tool schema 声明其持久化 sid/current-state——未知量只剩该持久化记录的当前字段值；『当前状态』这类问题只有状态记录能回答，实现源码/测试/文档在结构上不可能回答它。

## Short path
- get_goal：确认当前会话无活动 goal；未知量=设置是否发生在其他会话
- 按任务关键词查 event_stream/search_records：找到该 reminder 的成功创建回执，未知量收窄为『该记录当前字段值』
- 定位状态存储：以一次定向搜索或数据目录直读找到状态文件（本集即 data/schedule.json），命中实现语义内容（fsync/恢复测试等）即为偏离信号，立即停止该分支
- 防御性解析记录：先判明顶层结构是 list 还是 dict，再提取目标条目的 sid/repeat_interval/count/wake/下次触发/message 原文
- 用 message 原文与用户陈述（『每天3篇』）逐项对照，结合已取得的当日 STATUS/审核回执，输出：纠正前提+列出真实缺口+请用户在分歧处决策

## Stop conditions
- 状态记录已取得且其字段足以回答存在性/周期/已触发次数/下次触发/wake/message 内容等问题
- 记录确实缺失或不可读时，如实报告『无法核验当前状态』并仅给出创建回执级事实，不靠读源码推测

## Verification
- 答案中每个状态字段都能指认来自状态记录的具体条目/行，而非来自对机制行为的推断
- 对 wake 等语义字段的解释必须以工具 schema 为依据
- 回答中区分『记录上写的事实』与『记录之后发生的事』（如当日实际产出）

## Counterexamples
- 事件流/回执中找不到任何创建记录（如本集 streams=schedule,reminder 首查为空）：此时必须先广搜确认『是否创建过』，本方法不适用
- 用户问的是机制或行为成因（『为什么重启后提醒不触发』）：读实现与测试正是正路，读记录反而是绕路
- 状态记录存在已知并发写者且要下终局断言：仍读记录，但按 fresh-read-authoritative-record-before-finality-claim 在成稿时刻重读，属另一方法的叠加而非替代
- 记录字段与观察行为矛盾且无法用 schema 解释：才允许下钻源码查机制，作为例外分支而非默认入口
