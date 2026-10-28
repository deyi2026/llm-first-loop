---
method_id: goal-completion-audit-remote-ground-truth-over-ledger-status-14f50cf116c6
name: goal-completion-audit-remote-ground-truth-over-ledger-status
description: 用户问某持久化 goal 是否完成、台账已报 complete 或全部做完时，完成声明要分两层核验后再回答：每个交付项对应权威主线事实（该提交已在权威远端 main 上 + 同 SHA 最新 CI conclusion=success + 完成定义要求的审查回执）；每个版本化/对外可见声明（tag、Release、是否已 push）只以远端 tag 列表与 release list 的显式结果为准——checkpoint 散文与源码测试夹具里的版本 token（如 vX.Y.Z）不是发布存在的证据，checkpoint 的『未 push/已发布』是可能过期的过程断言。回答用逐项证据表，并显式划界：哪些涉权后续动作（打 tag、发起发布）从未执行、需用户授权，不折叠进『完成』。用已存在的权威外部结果把『状态位说完成』缩成『逐项可证交付』，避免凭台账复读或过度复验。
aliases: 怎么确认目标真做完了, 答完成前先验货, 没发过版被说成发过怎么核查, 测试夹具版本号误当真实发版, 完成汇报先对流水线和仓库真值
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:20761eb6-10e4-4e71-ae2b-0465510a97d8:1244:16113e002fe4500535b7
evidence_refs: learning:learn:3a45a0a768fe
created_at: 2026-10-28T01:14:50.033412+08:00
updated_at: 2026-10-28T01:14:50.033412+08:00
---
## Trigger
用户询问一个持久化 goal/任务集『完成了吗』，台账状态位已报 complete 或全部做完，且交付面含对外可见产物（远端提交、tag、Release/发布），或 checkpoint/子代理报告/回执散文中出现版本号与发布类断言

## Discriminator
checkpoint 与报告散文里的交付断言（『未 push』『已发布 vX』）以及源码测试夹具中的版本字符串，都是过程期文本；判别真值只需三类权威外部结果：与（先钉死的）权威远端的 rev-list 双向计数、远端 tag 列表、release view/list 的显式回执——版本存在性由它们裁决，台账状态位与夹具名不能

## Short path
- 读 goal 台账 + task frontier：枚举被声明的交付项，并抓出 checkpoint 里的范围断言（是否已 push、是否发过版、出现的版本号）
- 每个交付项做一次有界权威核对：对应提交在权威远端 main 日志中存在，且最新 CI run 的 headSha 与 HEAD 一致、conclusion=success；完成定义含审查则以回执文件在案为准
- 凡出现版本化/对外可见声明：查远端 tags 与 release 列表；显式 not found 或列表缺失即判定该版本从未存在，不再追夹具或散文来源佐证
- 用逐项证据表作答，显式纠偏 checkpoint 与地面真值的矛盾（如『未 push』实已同步），并写明涉权后续动作（发布）未执行、待用户指令
- 所有声明都取得一次权威匹配、矛盾已声明即停止；不重读产物全文复验内容

## Stop conditions
- 每个台账声明的交付项都取得一次权威地面真值匹配（提交在远端 + CI 绿 + 审查回执在案）
- 全部版本化声明的存在性已由远端 tag/release 列表裁决，矛盾已向用户显式声明
- 涉权动作边界已写明并交还用户决策，不再扩查

## Verification
- 先钉权威远端，再 rev-list --left-right --count 与 HEAD 比较 = 0 0
- 交付提交 SHA 出现在远端 main 日志；最新 CI run 的 headSha 等于该 SHA 且 conclusion=success
- 对每个被声称的版本：release view/list + 远端 tag 列表给出存在/不存在结论，负结论以显式 not found 为据而非推断

## Counterexamples
- 交付项纯内部且回执已内嵌内容身份（hash/version_token、进程身份核验）：回执即权威，再查远端属过度核验
- 用户问的是进度或『还剩什么』（活动 goal 续跑）：台账算术即答案，不做完成审计
- goal 完成定义只覆盖过程产物（写文件、落回执）且无对外可见后续面：状态位+回执已足够，本方法不适用
