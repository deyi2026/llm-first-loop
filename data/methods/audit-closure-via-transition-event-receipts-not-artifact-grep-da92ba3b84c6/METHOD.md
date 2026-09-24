---
method_id: audit-closure-via-transition-event-receipts-not-artifact-grep-da92ba3b84c6
name: audit-closure-via-transition-event-receipts-not-artifact-grep
description: 审计“某流程是否闭环/是否被用到”时，先把问题拆成阶段转移清单（如 save_candidate→record_use→record_qualification→activate），用统一事件流中该生命周期工具的 action 回执逐段证明转移发生过；『用了几次』只从 action 回执计数。不要 grep artifact 文本里的动作名来计数——正文提及≠发生（本例 grep 命中 6 个含 record_use 的文件但结构化 use 记录为 0）。各 store 的最新时间戳检索只用来补没有转移事件的阶段（如 self_eval/lesson 停摆多久）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7d3df8c3-848b-4bf3-b66b-1dbd2f791ac4:1221:69ebb986b44da54a66d9
evidence_refs: learning:learn:e78f118b62d9
created_at: 2026-09-23T16:34:02.749576+00:00
updated_at: 2026-09-23T16:34:02.749576+00:00
---
## Trigger
被问『X 流程闭环了吗 / 方法、经验有没有被用到』这类流程审计问题，且工作区存在逐条记录工具调用的统一事件流（action/tool 回执）

## Discriminator
事件流回执里已可见 action.tool_loop tool_call method_manage 等生命周期调用被逐条记录——说明阶段转移有一等回执可直接查询，先于对每个 store 做内容枚举；另一个判别信号：grep store 文件命中动作名 6 处但结构化决策 JSON 为 0，即『提及≠发生』

## Short path
- 从用户问题列出的阶段名导出需证明的转移清单（Episode 产生 / Reflection 运行 / candidate 全链 / use 反馈生效）
- 按工具名查统一事件流（workspace scope）中该流程生命周期调用的回执，一次拿到全链时间戳与首次发生时间
- 仅对无转移事件的阶段做各 store 最新时间戳检索（如 self_eval、lesson 的最后日期）
- 计数『用了几次』：统计事件流 action 回执条数；机制生效用运行时事实验证（当前进程 head 是否包含相关 commit），不用 artifact 文本 grep 计数
- 四段证据齐即停，输出每段状态+硬证据

## Stop conditions
- 所有阶段转移均已由事件回执或权威记录证明（发生/未发生/停摆时长）
- use 计数与生效性已由 action 回执和运行时事实双重确认，不再追加确认性查询

## Verification
- 事件流中的转移时间戳与 store 记录交叉一致（如 active 卡的时间戳）
- 计数口径复核：以 action 回执为准；与 grep 命中数不符时优先信回执并向用户解释差异（提及 vs 发生）

## Counterexamples
- 没有统一事件流或留存窗口覆盖不到要审的时间段→只能退回 artifact 时间戳/mtime 审计
- 问题问的是 artifact 内容质量而非『某动作是否发生过』→内容检索才是正确工具
- 事件流是采样/截断的（如 limit 30 条）→流内计数会低估，需结合 store 全量记录
- 单 artifact 的事实问题、无流程阶段概念→不适用本方法
