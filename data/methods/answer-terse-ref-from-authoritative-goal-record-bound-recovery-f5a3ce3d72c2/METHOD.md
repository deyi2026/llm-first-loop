---
method_id: answer-terse-ref-from-authoritative-goal-record-bound-recovery-f5a3ce3d72c2
name: answer-terse-ref-from-authoritative-goal-record-bound-recovery
description: 用户用极简指令引用一个当前会话缺失的清单/定义（如“收口前两个验项完成”），而活动 goal/task 权威记录已枚举数量吻合的条目且每条带时间戳完成回执时，第一跳的权威回执已足以作答：直接按回执逐条作答并显式声明映射假设与未复核项，请用户点名纠偏。对“恢复用户所指原文”的有界探测最多一次；工具回执证明该内容类不可恢复即停止，不换措辞/换入口重试同一 ref；也不得把核验规划反复写进裁决器占位而不实际发出命令。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d4b773f7-7796-4ff1-a76a-310f94b7feff:1005:f87699f7a4b7f0bfa443
evidence_refs: learning:learn:d41debbdaa23
created_at: 2026-09-25T14:45:48.062966+00:00
updated_at: 2026-09-25T14:45:48.062966+00:00
---
## Trigger
极简用户指令以序数词（前两个/第一个…）引用一个当前上下文不存在的清单或编号定义；同时存在活动 goal/task 记录，且回执中枚举的收口前置条目数与用户引用数吻合、均带时间戳完成证据、无 open 任务反证

## Discriminator
第一跳 get_goal/task_frontier 回执已同时给出：①条目数与用户引用数一致；②每条带 checkpoint 时间戳完成回执；③0 open / 全 done、goal_completion_ready=true。剩余唯一不确定是“用户是否另有所指”，而该问题被证明不可由恢复工具解决（convergence_decide/read 历史内容取不回），只能靠声明假设+请用户点名解决

## Short path
- 读权威 goal/task 记录，核对：枚举条目数是否与用户引用数吻合、是否均带时间戳完成回执、有无 open 反证
- 若吻合，作一次且仅一次有界探测恢复用户所指原文（如 read_evidence 单次调用）
- 探测失败或工具回执明确不返回该内容类 → 立即停止恢复，禁止换措辞/换入口重试同一 ref，也不得以‘还差一条未发出的核验命令’为由续跑裁决轮
- 按权威回执作答：逐条列完成证据，显式声明映射假设与未直接复核项（如 git 哈希、推送状态、原文不可恢复），请用户点名纠偏

## Stop conditions
- 权威记录条目与用户引用一一对上且全部带时间戳回执，且恢复探测已做过一次并失败
- 已决定作答后不再发起新一轮同源恢复尝试或占位性裁决轮

## Verification
- 答案中每条完成断言都能指回权威回执的具体 checkpoint/时间戳
- 未复核项在答案中如实列明，不以沉默冒充已核验
- 证据链中不存在对同一不可恢复 ref 的重复换措辞调用记录

## Counterexamples
- 权威记录枚举数与用户引用数不吻合（用户说三项、记录只有两项）→ 映射假设不成立，先请用户点名而非强行对齐
- goal 记录可能是陈旧快照且存在已知并发写者 → 必须先重读权威记录再断言完成（属 fresh-read-authoritative-record 场景，本方法不适用）
- 恢复探测一次即成功返回用户所指原文 → 以原文为准，放弃记录中的推断映射
