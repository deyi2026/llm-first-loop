---
method_id: refresh-generation-then-mutate-defer-to-async-receipt-1ee70fc36995
name: refresh-generation-then-mutate-defer-to-async-receipt
description: 对受管服务执行带 expected_generation 的变更（如重启）前，先取权威 status 拿到当前 generation 与各服务 restart_required，用准确值发起变更，避免因过期/猜测的 generation 被拒或重复取状态。若回执是异步受理并明确要求"立即结束本轮、勿轮询、下一轮用 action_id 查终态"，则把该协议当作权威指令：立刻结束本轮、不占锁不轮询，用延迟唤醒（schedule）把"查终态+下一个依赖动作+再次唤醒"整体编码进提醒，逐服务推进，直到全部目标服务 live git_head 与期望一致且 restart_required=false 再汇报。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6e0fb83b-03af-44ff-be33-c3498380b42f:1328:6fd8af536df07b076ed1
evidence_refs: learning:learn:22305e271800
created_at: 2026-09-20T21:22:57.819091+00:00
updated_at: 2026-09-20T21:22:57.819091+00:00
---
## Trigger
需要对受管服务执行 generation 校验的变更（重启/发布），控制面可能返回带两阶段等待协议的异步受理回执；或此前变更因 generation 不匹配、状态过期而被拒/重复查询。

## Discriminator
当时即可见的具体事实：status 返回的 deployment.generation 准确数值、各服务 restart_required=true 与 live/desired git_head 差异、以及受理回执明示"发起方应立即结束本轮、勿轮询本 action，下一轮用 action=status + action_id 查终态"。这三点分别把"传什么参数、动哪些服务、何时等待"直接定死，无需再枚举其他操作。

## Short path
- 取权威 status：确定当前 deployment.generation、各服务 restart_required 与 desired git_head 差异（未知量：准确 expected_generation 与需重启的范围）。
- 对单个目标服务发起变更，expected_generation 传刚取到的准确值；明确不动范围外服务（如 web）。
- 若回执为异步受理且要求结束本轮：立即结束，不轮询、不占 publish 锁；schedule 延迟唤醒，并把"查终态(action_id)→确认后重启下一个服务（同样先刷新 generation）→再次安排唤醒"写入提醒文本，保证计划不丢失。
- 唤醒轮用 service_control(status, action_id) 查终态；确认成功后才发起下一个服务的重启。
- 全部目标服务 live git_head==desired 且 restart_required=false 后停止并向用户汇报对齐结果与预期中断。

## Stop conditions
- 所有目标服务 live git_head 与 desired 一致且 restart_required=false。
- 终态查询显示失败或出现 admission_barrier 等需人工介入的信号。
- 用户中止或变更范围被修改。

## Verification
- 每次变更请求的 expected_generation 与发起前 status 的 generation 完全一致。
- 终态查询的 action_id 与受理回执一致且结果为成功。
- 最终 status 中每个目标服务 restart_required=false、live git_head==deployment.git_head。

## Counterexamples
- 工具是同步的、或回执明确允许/要求轮询进度时，不应机械结束轮次改用延迟唤醒。
- 服务间无依赖且控制面支持批量 target（且范围允许）时，逐服务串行+多次唤醒只增加时延，应一次批量发起。
- 操作本身不需要 generation 参数的一次性查询/读取，前置 status 刷新属于多余调用。
- 环境无 schedule/延迟唤醒能力时，应改为在下一自然轮次按 action_id 查询，而不是挂起等待。
