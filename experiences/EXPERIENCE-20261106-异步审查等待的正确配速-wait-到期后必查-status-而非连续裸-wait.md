---
title: 异步审查等待的正确配速：wait 到期后必查 status，而非连续裸 wait
scenario: review_admission 异步审查（waiting_protocol）或多审并行时，等待方在 wait(≤120s) 到期后未查 status 而是继续裸 wait，导致已完成的审查被晚发现数分钟；单审纯等待窗口无产出。
root_cause: ""
solution: 等待即轮询：每次 wait 到期 → 立即 status/job_output 一次 → 决定下一步；等待窗口填充只读收尾动作（task_state/经验沉淀/文档整理），但绝不触碰会改变审查绑定摘要的 git 状态。
evidence: "evidence://v1/4979659c1eb7a7f8334ac724b93dd0c083ce2925031b4a32fc3c81bb1c6302d7（第四轮 PASS 回执）；本 run 累计 wait 3360s 的 action_trace（15 次连续 wait(120) 无 status 穿插）"
tags: [review_admission, waiting_protocol, wait_pacing, 异步审查, 轮询]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-06T21:23:19.747311+08:00"
updated_at: "2026-11-06T21:23:19.747311+08:00"
supersedes: [EXPERIENCE-20261103-异步审查终态-wait-只做配速-status-才是完成信号-每次-wait-到期必须跟一次-sta]
---

反例：M2 合并闸第四轮审查（subagent_ece469d269e3，预计 1855s）发起后，我连续 15 次 wait(120) 空转 ~17 分钟，没有按协议穿插 status 检查；事后一查已 PASS——若每 2-3 分钟查一次可提前数分钟进入下一环，且长时间无观测的等待掩盖了「提前完成/卡死」两种可区分状态。

改进模式（此后照做）：
1. wait 配速 = 每次到期后必调一次 review_admission(status)（或 job_output），不做连续裸 wait；
2. 前段（预计时长的 40%）每 2 分钟查一次，后段每 3-4 分钟一次；预计 30 分钟的审查一般 12-20 分钟出结果（历史：69813 字符 12 分钟，185591 字符 ~17 分钟）；
3. 若连续 3 次查询无状态推进（仍 running），再退回长间隔等待，不需要每分钟轮询；
4. 同时可利用等待窗口做只读收尾（task_state 更新、经验沉淀、报告整理），但禁止任何 git 状态变更（full_test 资格绑定树摘要）。