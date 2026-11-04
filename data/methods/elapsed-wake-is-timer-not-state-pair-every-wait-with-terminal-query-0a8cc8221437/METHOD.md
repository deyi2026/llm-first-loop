---
method_id: elapsed-wake-is-timer-not-state-pair-every-wait-with-terminal-query-0a8cc8221437
name: elapsed-wake-is-timer-not-state-pair-every-wait-with-terminal-query
description: 无 job_id 的阻塞 wait 只是墙钟计时器：wake_reason=elapsed 到期对目标任务状态零信息，连续多次 elapsed 不构成『仍在运行』的证据，只证明计时器在工作。正确协议是每个 elapsed 到期后立即跟一次终态查询，终态结论只能出自终态查询回执或 job 绑定 wait 的 job_terminal 真唤醒；等待 execute_command job 时反向：必须带 job_id，job_terminal 即终态。当问题是『要不要调大等待秒数减少无效等待』时，先分类缺陷：回执语义误读是协议缺陷，调 seconds 无效；若接口回执/工具描述未写明等待协议，沉淀经验并向工具面提演进建议，不自行改 schema。
aliases: 白等很久才发现早就完成了, 等待到期不等于还没跑完, 轮询等待参数该怎么调, 异步子代理轮询节奏, 等待被唤醒后下一步查什么
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:73172f2a-c1f6-4868-9611-d4af1d463c48:3061:12b66d55090dd42d0fa3
evidence_refs: learning:learn:966b81b27126
created_at: 2026-11-03T23:18:42.080566+08:00
updated_at: 2026-11-03T23:18:42.080566+08:00
---
## Trigger
对没有 job_id 绑定的异步对象（如准入审查 child、外部审批）用阻塞 wait(seconds) 做配速等待，回执 wake_reason=elapsed 到期唤醒；或用户询问等待参数是否需要调整以减少长时间无效等待

## Discriminator
wait 回执的 wake_reason 字段自证语义：elapsed=纯墙钟到期，对目标任务状态零信息（wait 的 schema 已写明省略 job_id 时不监视后台任务）；job_terminal=进程终态真信号。连续 N 次 elapsed 只证明计时器在工作，不证明任务未完成——缺陷在等待协议，不在 seconds 数值

## Short path
- 第一个 wake_reason=elapsed 到期：按 schema 判定该唤醒不含目标任务状态，未知量仍是『任务是否已终态』
- 立即对该对象发一次终态查询（如 status(child_id)）；终态只能由此回执或 job_terminal 唤醒证明
- 未终态则重复 wait→status 配对；任意两次 wait 之间必须夹一次状态查询（配对不变量），连续 elapsed 不得累积
- 终态到达即读回执点名工件并停止；若等待对象是 execute_command job，反向规则：wait 带 job_id，job_terminal 唤醒即终态，无需补查
- 若工具回执/描述未写等待协议：沉淀经验卡并向工具面提演进建议补协议文案；不自行改 schema，也不用调大 seconds 代替协议

## Stop conditions
- status 回执（或 job 绑定 wait 的 job_terminal）给出终态后，停止一切 wait 与轮询
- elapsed 到期永不构成『继续等』或『已失败』的独立依据；不得以连续 elapsed 次数推断任务状态

## Verification
- 复查轮询轨迹：任意相邻两次 wait 之间恰有一次终态查询
- 最终结论的出处只能是终态查询回执或 job_terminal 唤醒，而非 elapsed 计数或时长直觉
- 若用户问的是参数：确认结论已区分『秒数上限不足』与『回执语义误读』两类缺陷，只对前者调参数

## Counterexamples
- wait 绑定了 execute_command 的 job_id：wake_reason=job_terminal 在任务完成时真唤醒（本集 ci_gate 84.5s），无需再补 status
- 终态查询入口自带阻塞等待参数（如 subagent_result(wait_seconds)）：直接用它一次完成等+查，不要另起 timer wait 交替
- 浪费确实源于秒数上限低于任务实际时长（固定 3 分钟任务配 120s 上限）：此时调参数或换长阻塞入口才是正解，配对协议救不了
- 同步短任务根本不需要 wait 配速：直接调用即可
