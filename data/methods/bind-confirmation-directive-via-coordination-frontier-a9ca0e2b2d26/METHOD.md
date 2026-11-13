---
method_id: bind-confirmation-directive-via-coordination-frontier-a9ca0e2b2d26
name: bind-confirmation-directive-via-coordination-frontier
description: 新会话收到极简确认型指令（如『按建议顺序执行』）时，指令文本是对上一轮『列清单+等待确认』回复的回指，本身不含可检索线索。不要按指令关键词搜 evidence/archive（必然 miss），也不要先读 help_inbox 等无关队列：先从 coordination_status 找交互前沿——最新 checkpoint 且仍有 open/ready 任务的 goal——再在该 checkpoint 时间窗内拉 llm_response，定位以『确认后我立即开跑 TASK-xxx』类等待确认语收尾的回复原文，以其清单顺序执行；尚在执行中的并发会话未产出终态建议，不作为绑定对象。与『premise-freshness 复核』卡互补：本卡解决指令指代对象是谁，那张卡解决执行前环境前提是否仍真。
aliases: 按建议顺序执行先锚定建议出处, 确认型极简指令先查最近checkpoint的goal, 用户让执行建议清单先找回等待确认的那条回复, 新会话执行前一轮建议先看goal前沿任务, 指令关键词搜不到就按checkpoint时间窗拉回复
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a2ff782e-c9a9-4539-9f63-0afe510af460:0:55ab2c1f53f473c0bc21
evidence_refs: learning:learn:7f71cc22f9ad
created_at: 2026-11-12T23:33:58.514619+08:00
updated_at: 2026-11-12T23:33:58.514619+08:00
---
## Trigger
新会话（task_state 为空/失败）收到极简确认型指令（『按建议顺序执行』/『就按这个来』），其指代对象是上一轮交互中某条『列建议清单并等待确认』的助手回复，且工作区存在多 goal 协调面（coordination_status 可用）

## Discriminator
coordination_status 里『最新 last_cp 时间 + tasks open/ready>0』的那一个 goal 即交互前沿；待绑定的回复特征是以等待确认语收尾（如『确认后我立即开跑 TASK-xxx 采集』），其内容不含用户指令的关键词，因此按用户措辞搜索结构性 miss；且最近 checkpoint 的 goal 前沿任务 ID 应与清单下一动作对得上

## Short path
- task_state 读失败→判定新会话，指令是回指性确认；未知量=建议清单是哪一条
- coordination_status→取『最新 checkpoint 且 open/ready>0』的 goal 作为前沿；排除仍在执行中的并发会话（未产出终态建议）
- goal read 该前沿 goal→拿到 open task ID 与跨会话写权限约束（哪些动作本会话无权做）；未知量=清单具体内容与顺序
- event_stream 用 since≈前沿 checkpoint 时间窗拉 llm_response content，定位以等待确认语收尾的回复原文（用时间窗过滤，避免与自身查询串自匹配的宽 content 查询）
- 按清单优先序执行本会话有权做的项；无权项（如 owner 会话的任务翻转）写成显式收口说明上报，并标注绑定依据请用户纠偏

## Stop conditions
- 找到唯一等待确认回复，且其清单项与前沿 goal 的 open task ID 对应一致→停止检索，开始执行
- 多个前沿候选或时间窗内出现多条待确认回复且无法唯一分辨→向用户请求消歧，不猜测绑定
- 清单动作的前提（权限/环境/归属会话）与回复假设不符→暂停机械照做，转入前提复核

## Verification
- 绑定的回复中列出的下一动作与 goal 记录的 open/ready task ID 一致
- 最终报告显式写出绑定依据（哪条回复、什么时间、何等待确认语）并请用户纠正可能的错绑
- 无权跨会话执行的步骤已明确移交说明，未发生 cross_session_write_denied 类失败

## Counterexamples
- 用户消息自含建议内容（无回指）→直接执行，无需绑定
- 指令以计划阶段标签/文档名指代→改用 docs 命名空间卡定位权威定义
- 无 goal/checkpoint 协调面→改用 resume-continuation 卡：搜索 miss 回执中列出的权威文档参考
- 并发会话仍在跑但从未给出任何建议清单→不能绑定到它；前沿只能是已有终态 checkpoint 的 goal
- 时间窗内存在多条不同会话的待确认回复且任务 ID 对不上→歧义未消解前不执行
