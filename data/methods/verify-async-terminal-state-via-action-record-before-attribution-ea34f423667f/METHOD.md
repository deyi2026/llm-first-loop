---
method_id: verify-async-terminal-state-via-action-record-before-attribution-ea34f423667f
name: verify-async-terminal-state-via-action-record-before-attribution
description: 异步控制动作（restart/publish 等）的受理回执只表示已排队，不是终态。当用户报告预期效果未发生（服务仍跑旧版本、队列不动）时，第一步应沿回执给出的 action_id 查权威终态记录（status/detail/next_step），而不是先做事件流检索或全目录 grep，更不能在未查终态前向用户断言等待机制。失败记录通常自带 remediation（如 git_head mismatch → 先 publish 推进 desired 再 restart），沿它执行即可。另：跨源时间戳先统一时区再算差值，避免虚构停摆时长。
aliases: 重启完还是旧版本 怎么回事, 回执只是排队 不是终态, 按 action_id 查终态记录, status detail next_step, git_head 不一致 先 publish
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:858:cf30b371cf28d12a9df6
evidence_refs: learning:learn:8c1538988615
created_at: 2026-09-24T00:24:03.014982+00:00
updated_at: 2026-10-23T05:53:08.417104+08:00
---
## Trigger
用户或系统观测到某个先前已受理的异步动作迟迟未产生预期效果，需要归因；或即将向用户解释某异步动作为何未生效/仍在等待，且手上已有该动作的 action_id 或受理回执。

## Discriminator
受理回执本身写明终态查询通道（如 service_control(action=status, action_id=...)）且声明了具体等待条件（如先等 requester 会话结束再等目标空闲）。若该等待条件已被观测事实满足（requester 会话早已结束）而症状仍在，则『仍在等待』假设被证伪，必须读记录；同时存在按 action_id 命名的权威动作记录（如 service-control-actions/<action_id>.json），它是比事件流/全目录检索更窄的下一跳。

## Short path
- 症状出现后先只解决一个未知量：该 action 的终态是什么——用回执给出的 status 通道或按 action_id 读权威记录，不做事件流/全目录宽检索
- 从记录读 status/detail/next_step；若 failed 且 next_step 给出修复路径（如先 publish 把 desired 推进到当前 HEAD），先核对前置条件（如 tracked 树干净）再执行修复
- 以新 generation 重新受理动作；对带枚举参数的接口先确认参数域（target 必须属于合法集合）再调用
- 轮询终态至 succeeded 或回执明示的设计内等待态，并用运行时证据（新进程 PID、journal 消费记录、版本自检）确认生效
- 跨源时间戳比较前统一时区，再下停摆/滞后 N 小时的结论
- 终态与运行时证据齐备后才向用户报告机制，并显式撤回先前无证据的断言

## Stop conditions
- 权威动作记录显示 succeeded，或其声明的等待条件经独立观测确认仍真实成立
- 运行时证据（进程/日志/版本）与记录状态一致
- 用户所需的归因已被记录的 detail + next_step 完整解释且修复已受理

## Verification
- action 记录的 status/detail、受理回执、运行时观测三方一致
- 修复后用新的 action_id 复验终态，而非沿用旧受理回执当作结果
- 任何『等待中/停摆 N 小时』的说法都能指到具体记录字段或统一时区后的时间戳

## Counterexamples
- 动作是同步的，工具响应已直接包含最终结果——无需二次查终态，直接分析即可
- 症状与任何已受理动作无关（队列不动是上游根本没有提交）——应直接查调度器/消费者存活，而非锚定 action 记录
- 回执声明的等待条件确实仍成立（requester 会话仍在运行）且无反证——此时『等待中』是有据结论，再 publish 新 generation 或重复受理属于 post-sufficiency 噪声
- 按 action_id 找不到权威记录（缺失或损坏）——事件流/全目录宽检索才成为正当的第一步
