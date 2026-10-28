---
method_id: remeasure-declared-system-state-over-session-recall-eae7e54ef71d
name: remeasure-declared-system-state-over-session-recall
description: 当用户对 repo 内自维护系统（有落盘状态文件+生成脚本，如打分/索引管线）索要下一步建议时，所需事实是系统的当前状态，而非上轮会话记忆：上一轮的数字本身只是对状态文件的过期快照。判别要点：(a) 自己首轮检索用的就是字面 artifact 名，说明目标位置可直接定位；(b) evidence 水合若显示上轮事实来自 execute_command 对数据文件的统计，则该事实可低成本重测。动作：按已知文件名一次定位（排除 .releases/.worktrees 等历史副本）→ 读生成脚本 docstring 的 Reads/Writes 契约 → 一次脚本化读取当前计数/分布/时间戳 + 一次 grep 查消费方 → 以带时间戳的新鲜测量作答，不做会话考古。与 fresh-read-authoritative-record（成稿前重读权威记录）和 named-provenance 续跑法互补：本条在规划期就决定选重测而非回忆。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72b1f325-1293-4022-9fb8-46f58685873e:407:8666c8e3cc08e56db0d5
evidence_refs: learning:learn:7e9bf87cfe0d
created_at: 2026-10-17T13:35:51.753881+08:00
updated_at: 2026-10-17T13:35:51.753881+08:00
---
## Trigger
用户对 repo 内自维护系统（有落盘状态文件与生成脚本，如索引/打分管线）要求『下一步建议/继续推进』，所需事实是该系统的当前状态（计数、分布、产出是否被消费）；且自己的首轮检索动作已经在用具体 artifact 名（如文件名）作为查询词。

## Discriminator
目标事实是否『当前可重测』：首次 search 使用的就是字面文件名，证明 artifact 名已知、可直接定位；且 evidence 水合预览显示上轮结论来自 execute_command 对数据文件的统计——即任何会话回忆值都只是过期快照，对『当前状态』类问题没有独立价值。二者任一成立，即应跳过记忆恢复、直接重测。

## Short path
- 用已知 artifact 名做一次直接定位（find/grep，排除 .releases/.worktrees 等历史副本），同时拿到状态文件与生成脚本路径
- 读生成脚本头部 docstring 的 Reads/Writes 契约，确认权威状态文件位置与刷新方式（atomic 重写、时间戳字段）
- 一次脚本化读取当前状态：总数/已评/未评/分布 + 产出文件头部 + 重建时间戳
- 一次 grep 检查产出在生成器目录之外是否有消费方，判断闭环止于何处
- 以新鲜测量+时间戳构成建议依据；上轮记忆只用于界定话题范围，不引用其数字

## Stop conditions
- 已获得带时间戳的当前状态测量与『有无消费方』的结构事实，足以支撑建议优先级排序
- 定位失败或落盘状态与脚本声明的契约不符（此时才转入目录级宽探索或根因分析）
- 发现目标事实其实不可重测（外部一次性事件、口头偏好）→ 回退到 evidence/记忆恢复路径

## Verification
- 建议中每个数字都能指到本次会话直接读取的数据文件，并标注测量/重建时间戳
- 所读状态文件清单与生成脚本声明的 Writes 一致；『无消费方』结论来自排除生成器目录后的 grep
- 不复述任何未在本次重测中验证过的上轮数字

## Counterexamples
- 目标事实不可重测（用户上轮口头偏好、一次性外部事件）→ 记忆/evidence 恢复仍是正解，本条不适用
- 状态复现昂贵（长跑 benchmark、远端重算）→ 复用已存快照更划算，但须标注 freshness/task_applicability=not_evaluated
- 用户问的就是『上次我们得出什么结论』→ 任务本身是回忆而非测状态，本条不适用
- search 回执是权威 miss（明确列出索引范围且不含该名）且手头无任何路径线索 → 才需要目录级 broad discovery
