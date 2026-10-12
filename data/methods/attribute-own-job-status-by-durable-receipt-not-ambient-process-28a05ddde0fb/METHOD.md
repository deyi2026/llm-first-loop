---
method_id: attribute-own-job-status-by-durable-receipt-not-ambient-process-28a05ddde0fb
name: attribute-own-job-status-by-durable-receipt-not-ambient-process
description: 被问『你启动的后台任务出结果了吗』且手头只有 ps/日志等环境观测时：先用自己的任务锚点（job 句柄、完整启动命令、启动时间）核对观测对象身份。锚点不匹配的进程是别人的，不要吸收为『我的任务还在跑』，更不要据此改写自己的时间线记忆；自己任务的状态一律以 durable 回执为准，句柄缺失时用 tool_history 按工具名确定性找回，而不是对 evidence 库猜关键词。本集因把 9:09 的外来 pytest 误认成自己的回归并公开改口『9:09 而非 9:04』，后续多花 search_evidence miss + 多轮历史水合才纠正，同一时间线被两次公开改口。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8098b445-b87e-4252-a938-91924f37f4db:214:04eeeb21bd53ffa7fe03
evidence_refs: learning:learn:5a596249e1fa
created_at: 2026-10-07T11:29:20.666495+08:00
updated_at: 2026-10-07T11:29:20.666495+08:00
---
## Trigger
用户询问自己启动的后台/异步任务（回归、部署、批处理）的状态或结果，同时存在环境级观测（ps/日志/队列）看似显示『它在跑』，且该观测的身份锚点（命令行签名、启动时间）尚未与自己任务的启动锚点核对。

## Discriminator
当时已在上下文中的冲突事实：ps 显示的 pytest 启动时间 9:09 与自己记忆的启动时间 9:04 不一致，命令行 flags（tests/ -q -x --ignore=tests/perf）从未与自己任务的启动命令核对过；同时自己明确知道回归是用带 durable 回执的后台 job 启动的。两者叠加说明该进程身份未证实——『我的任务状态』与『存在一个 pytest 进程』是两个问题，回执才是前者的权威来源。

## Short path
- 先列出自己任务的锚点：job 句柄、启动完整命令、启动时间；记不全就按工具名查一次 tool_history 找 job_output 调用（确定性恢复，不猜关键词搜 evidence）
- 对句柄直接 job_output 读状态/exit/计数——这一步即回答『出结果了吗』
- 对 ps 等环境观测做锚点匹配：命令签名或启动时间任一不匹配 → 归类为外来进程，只引用其 cmdline 作为环境事实，不改写自己任务的时间线
- 任务的另一部分（如 diff review）直接基于已获取 artifact 分页水合完成，不与状态考古纠缠
- 成稿：状态句引用回执（job id/exit/通过数），外来进程写明判定依据，review 发现逐条引用 hunk

## Stop conditions
- 已取得自己 job 的 durable 回执（状态、exit code、测试计数），停止一切状态考古
- 环境进程已按锚点判定 mine/foreign，除引用 cmdline 外不再深挖外来进程
- 交付物所需 artifact（diff/代码段）内容已读齐

## Verification
- 每句状态结论的出处是回执字段（job id、exit、passed/skipped 数），而非 ps 快照或记忆
- 外来进程的归类写明依据（签名/时间不匹配），未以环境观测覆盖自己的启动记忆
- review 每条发现给出 hunk/行号依据；未实读的疑点显式标注 unverified

## Counterexamples
- 任务不是自己启动、也无 durable 句柄（如同事口述『有回归在跑』）：ps 就是唯一证据，如实报告并标注归属未知即可，本方法不适用
- 环境观测与自己任务锚点完全匹配（相同 flags、相同启动分钟）：ps 可直接回答『还在跑』，中间态无需阻塞等回执
- 用户问的是机器/会话整体负载而非某个具体任务：先看 ps 本来就是正确路径
