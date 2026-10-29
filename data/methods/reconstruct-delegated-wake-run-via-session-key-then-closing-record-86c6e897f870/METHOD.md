---
method_id: reconstruct-delegated-wake-run-via-session-key-then-closing-record-86c6e897f870
name: reconstruct-delegated-wake-run-via-session-key-then-closing-record
description: 接手或被问下一步时，若一段由调度 wake 以 delegated 方式执行、结果未知的无人值守 run 已经跑过，不要用宽窗口翻共享事件流（会被并行会话刷屏，甚至把他方 tool_failure 误归属给目标 run）。wake 回执本身携带身份键：session id、起始时间戳、delegated 标记；用它们把历史查询圈定到该 run，一次拉全轨迹（做到哪步、在哪停摆）。见到停摆/结束后，优先读 run 自己持久化的收口状态记录拿全部终局（探针结果、门禁 verdict、哪些动作未执行），再把承重断言与远端 ref/HEAD 等一次直接真值对账，一致即停止发现、进入建议。与『状态问答直接读管线核验工件』互补：那边已知工件存在，这边先靠回执键发现轨迹与收口。
aliases: 查委派wake那轮干到哪步, 接手半路停摆的委派run, 事件流先按session圈定再翻, 别的会话报错别算到wake头上, 收口记录跟远端对上再建议, 上轮唤醒推进到哪了
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:25e48ad9-7d56-4793-9a70-4c63d9502373:1947:5d357bd9c814c238ac68
evidence_refs: learning:learn:9d9010f37d4f
created_at: 2026-10-29T08:18:10.396725+08:00
updated_at: 2026-10-29T08:18:10.396725+08:00
---
## Trigger
调度 wake 以 delegated=1 触发过一段执行多步计划的无人值守 run（或等价的委派执行），当前会话不确定它实际推进到哪一步、各步终局如何，需要先重建事实才能给建议或避免重复执行/漏步骤；且共享事件流中还有其他会话在并行产生事件噪音。

## Discriminator
触发回执（schedule.wake 事件行）当时就已携带 session=<该 run 的 id> 与精确起始时间戳。按 scheduler-sid 查询只会命中调度生命周期事件，按最近窗口不限定性拉取会混入并行会话事件，身份键在手即足以把『最近发生了什么』缩成『这条 run 发生了什么』。

## Short path
- 用一次权威状态读取核对计划的静态检查点（服务收敛、远端 ref、本地 HEAD），建立『世界现在什么样』
- 按 sid 查 wake 事件：确认已触发、delegated，并从回执行取 session id 与起始时间戳
- 用该 session id 作 query、since=唤醒时刻，拉目标 run 自己的完整轨迹（执行了哪些步骤、轮询、失败点），而非拉宽窗口
- 轨迹显示 run 停摆或结束后，读它持久化的收口状态记录，一次取得全部终局（探针结果、审查 verdict、未执行动作），不逐条挖异常日志
- 把收口记录的承重断言与第 1 步的直接真值逐条对账；一致即停止发现，输出下一步建议

## Stop conditions
- 计划中每一步的终局（已做+结果 / 未做 / 被门禁拦）均已由收口记录或圈定轨迹给出，且承重断言已与一次直接真值读取对账一致
- 确认 run 未持久化收口记录后，不再轮询等记录，改以圈定轨迹+直接真值收口

## Verification
- 收口记录的关键断言逐条复核：声称未执行的动作看权威侧状态（如远端 ref 未动）、声称的对象身份看本地真值（如 HEAD）、声称的收敛看服务状态
- 轨迹终点与记录落盘时间之间无未解释空档，且纳入归因的失败事件其 session 键确属目标 run

## Counterexamples
- 单会话工作区、无并行噪音：直接拉最近窗口即可，键控圈定是多余开销
- 委派 run 崩溃前未写任何收口记录：读记录这步不存在，终局只能由圈定轨迹+直接真值判定
- wake 回执里的 session id 与实际执行事件的记账 session 不一致（委派另起子会话）：按回执键圈定会漏事件，需按事件内容（命令工作目录/目标名）核对归属
- 用户只问某个具名单次动作是否生效：走该动作的具名终态入口做两未知量拆分即可，无需重建整条 run 轨迹
