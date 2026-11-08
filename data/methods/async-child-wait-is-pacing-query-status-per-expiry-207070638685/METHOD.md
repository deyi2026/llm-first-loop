---
method_id: async-child-wait-is-pacing-query-status-per-expiry-207070638685
name: async-child-wait-is-pacing-query-status-per-expiry
description: 等待异步 child（无 job_id 的子代理/审查类）时，计时型 wait 的到期返回不是完成信号：wake_reason=elapsed/timeout 只说明计时到点，不携带终态。按提交回执里显式声明的 waiting_protocol 执行——wait 仅作定速，每次到期后立即对回执指名的状态查询面取一次真实 state；非终态重复该轮，终态立即消费结果（当资格会因树漂移失效时尤需快）。同时判别 wait 句柄两类形态：带 job_id 的后台 job 会以 job_terminal 唤醒并附 exit，连排 wait 合法；无 job_id 的异步 child 终态只能来自状态查询面。
aliases: 等待空转十几分钟, 干等子代理不查状态, 连发 wait 干等, 异步任务等多久查一次, 子代理等待节奏
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:3319adeb-e84e-4f85-ae10-8306e3d98fb1:2070:1cebec88cec305135346
evidence_refs: learning:learn:75bd80f5baf6
created_at: 2026-11-06T22:25:30.046938+08:00
updated_at: 2026-11-06T22:25:30.046938+08:00
---
## Trigger
异步 child 在途（提交/受理回执无 job_id，属子代理、外部审查、评测类），需要等其终态；且回执已显式写出等待协议：wait 仅定速、终态须以指名状态动作获取。

## Discriminator
提交回执中明文的 waiting_protocol（『指定状态动作是唯一完成信号，wait 的到期只表示计时到点，每次到期后调该动作取终态』），以及 wait 回执自身的形态：仅 elapsed/timeout、无 state/exit 终态字段——纯计时器返回。二者在开始等待前均已可见。

## Short path
- 从提交回执提取三要素：定速上限（如 seconds<=120）、状态查询动作与 child 标识、终态字段名
- 每轮循环：wait 到期 → 立即对状态面查询一次，读真实 state；不连发第二次裸 wait
- 非终态→重复该轮；状态面给出终态→立即消费结果（如趁资格有效跑下游门禁）
- 若句柄是带 job_id 的后台 job：wait 会以 job_terminal 唤醒并带 exit，改回连排 wait 即可，无需逐次插查

## Stop conditions
- 状态面回执给出显式终态（PASS/FAIL/REVISE/done 等），且 child 标识与提交回执一致
- 达到协议声明的重试或预算上限，停止轮询转升级/重发

## Verification
- 账本中每次 wait 到期后都对应一次状态查询记录；终态结论出自状态面回执而非计时返回
- 核对终态回执的 child 标识与提交回执一致，防止把旧轮或他人会话的终态当成本轮结果

## Counterexamples
- 带 job_id 的后台 shell job：wait 自身返回 job_terminal+exit，连排 wait 是正确姿势，逐次插状态查询反而多余
- 任务书以『等待参数+次数上限』定义轮询预算时，按预算计数法处理（bounded-poll 类方法），不适用本方法的每到期必查
- 同步或预计亚分钟级的快任务：一次短 wait 后查一次即可，多轮 wait-status 循环是浪费
