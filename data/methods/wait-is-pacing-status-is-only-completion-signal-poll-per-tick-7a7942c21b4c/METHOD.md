---
method_id: wait-is-pacing-status-is-only-completion-signal-poll-per-tick-7a7942c21b4c
name: wait-is-pacing-status-is-only-completion-signal-poll-per-tick
description: 异步审查/门禁子代理没有 execute_command 的 job_id：wait 只做墙钟配速，wake_reason=elapsed 仅表示计时到点，既非失败也非完成；终态只能靠 review_admission(action=status, child_id=…) 主动取。且实际审查时长常远小于回执的 estimated_seconds（估 13~30 分钟、实际 2~7 分钟），若按估计值排程首查或拉长复查间隔，会像本集第 5 轮那样漏查 50 分钟。判别事实就写在 accepted 回执的 waiting_protocol 字段里：每 1~3 个 wait 必夹一次 status。
aliases: 审查没出来要不要继续等, wait 到点了但没结果是不是设置错了, estimated还没到要不要先查status, 异步审查子代理多久查一次状态, wake_reason elapsed 什么意思, 审查比预计快很多早结束了怎么办
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6b58eeb0-73eb-421f-ace1-50ae51782327:3410:5cdde1e20e3bb8e59f94
evidence_refs: learning:learn:f994c7e8c24b
created_at: 2026-11-08T23:02:46.702222+08:00
updated_at: 2026-11-08T23:02:46.702222+08:00
---
## Trigger
向异步审查/准入子代理提交受保护动作（git push 等）后，accepted 回执含 child_id、review_budget.estimated_seconds 和 waiting_protocol（提示用 wait(seconds<=120) 配速、到期后调 status 取终态），需要决定等待与查询节奏时

## Discriminator
accepted 回执的 waiting_protocol 明示三点：审查是异步 child、无 job_id；status 是唯一完成信号；wait 的 wake_reason=elapsed 只表示计时到点。叠加本 run 已观测的先例：实际完成时长（2~7 分钟）常远小于 estimated_seconds（数百至上千秒），说明估计值只能当日程上限、不能当首查排程依据——首查应尽早、复查按 wait 节奏走而非按估计走

## Short path
- 提交审查后在 accepted 回执中取 child_id 与 waiting_protocol，确认完成信号通道只有 action=status
- wait(seconds<=120) 单次配速，到期即调 review_admission(action=status, child_id=…)；每 1~3 个 wait 必查一次 status，绝不按 estimated_seconds 推迟首查
- 非终态→继续 wait→status 循环；PASS→立即消费：受保护动作（git push）必须单条命令提交，与其他命令串联会被 Host 准入阻断（复合命令须拆分逐条）；推完即提交下一段审查，段边界用 git log <remote_commit>..HEAD 枚举
- FAIL/REVISE→按 findings 修复后重算候选 SHA 再送审；全程把『连续 wait 不查 status 的批次数』压在 3 以内

## Stop conditions
- status 回执进入终态（qualification=PASS/FAIL）：本轮轮询停止；终态回执是签发时点的合同快照，幂等重poll 不会补出新字段
- 所有段推送完成且 origin/main 与分支 HEAD 一致，转入尾程（构建/发布/汇报）
- status 显示运行级失败（child 死亡/超 deadline）：停止轮询，按失败类别改走重发或分段

## Verification
- 消费 PASS 前：status 回执的 candidate_sha256 与本段 target、push_src_commit 一致，consumable_scope 覆盖拟执行动作
- 推送回执的 pre-push range 前沿等于上一段已推 commit（链式推进无跳段）
- 自检零漏查：任意连续 3 次 wait 之间至少夹一次 status 调用；PASS 实际耗时与估计值偏差大不改变节奏

## Counterexamples
- 平台 wait 本身携带子代理完成唤醒（wake_reason=child_done 类语义）：完成信号已在 wait 回执内，逐 tick 查 status 冗余，应按唤醒语义行动
- 任务书明确给出轮询预算（等待参数+次数上限）：应按预算计数阻塞轮询并尊重上限，而不是无限逐 tick 查询
- 同步审查（start 调用直接返回终态）或 estimated 极短（<120s）：一次等待或直接取结果即可，无需 wait/status 循环
- status 调用有严格配额/成本约束：应拉长间隔并优先用长 wait，而不是每 tick 必查
