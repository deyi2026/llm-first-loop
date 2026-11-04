---
method_id: stale-handoff-state-verify-pipeline-terminals-before-executing-3ab4aac10609
name: stale-handoff-state-verify-pipeline-terminals-before-executing
description: 中断后按旧 handoff/task-state 快照续跑时，快照里的『进行中句柄+后续管道』（审查→push→publish→restart→汇报）可能在中断前就已全部完成。回执自带的 applies_to_current_run=false 或句柄 not-owned 已宣告该计划属于旧 run：把每条待办转成它的只读终态观测量（远端 tip、部署 generation+verify、具名测试读数）逐条核对，已达标者划掉、只处理真实残差（清理/汇报），不重执行受保护动作、不诊断伪失败、不重跑已死的审批。
aliases: 续跑时先看上轮是不是已经干完了, 继续之前先对远端真值再决定推不推, 旧交接状态里的待办还成立吗, 中断恢复先核对部署与远端, 别把已完成的收口当成在途审批
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:80a9ad77-9a07-4f8b-9da4-49adb180bd96:1306:141eed6d34638093f34e
evidence_refs: learning:learn:07cb41bc41a3
created_at: 2026-11-04T15:22:35.558704+08:00
updated_at: 2026-11-04T15:22:35.558704+08:00
---
## Trigger
极简续跑指令（如『继续』）命中一份前次运行留下的任务状态快照，其正文列出『进行中句柄 + 后续待办管道』，且回执带 applies_to_current_run=false、run_generation 与当前不符、或接手 in-flight 句柄被拒（not_owned）等机器级陈旧信号。

## Discriminator
两个当时已可见的事实：①状态回执的机器字段（applies_to_current_run=false、run_generation 异于当前 run）直接宣告『进行中』描述的是旧 run 的计划；②管道每一步都存在单次只读可达的终态面——远端 tip（ls-remote）、部署 status 的 git_head/generation/verify.outcome、具名测试文件的实际 pass/fail。二者合起来足以把『要不要执行整条管道』缩成『逐条核对终态』。

## Short path
- 读 handoff 状态：列出待办管道各步并标注各自的终态观测量；见到 applies_to_current_run=false 时，先把整份计划当待证假设而非当前义务。
- 逐条单次只读核对：ls-remote 取远端 tip 对比本地 HEAD；service status 核 git_head/generation/verify；按旧断言点名的方式重跑具名测试文件。
- 已达终态的步骤从计划划掉：不发起 push/restart 等受保护动作，不接手已死 run 的审批句柄，也不把旧断言（如『两条既有红』）当作现存问题去诊断。
- 只对确认存在的缺口执行动作（如删除临时探测脚本）；受保护动作仍单独走准入，不做 compound 命令。
- 以当次回执为证汇报完成态，并如实登记仍未实施的范围（如闸门未满足的 B-4/B-5）。

## Stop conditions
- 每条待办均被终态观测判为『已完成』或『确认仍缺且已处理』。
- 汇报所需事实全部有本次回执支撑，不再引用旧快照中未复核的断言。

## Verification
- git ls-remote 取得的远端 tip 与本地 HEAD 逐位相等（不信任 tracking ref 或状态快照里的『待推送』说法）。
- 部署状态回执的 git_head/generation 与目标提交一致，且 verify.outcome=ok、restart_required=false。
- 具名测试的实际读数覆盖或推翻旧断言（如 50P/2F 变 52P/0F 时，能指出消除既有红的来源提交）。

## Counterexamples
- 状态属于当前 run（applies_to_current_run=true、in-flight 句柄归本会话所有）：应按 deadline 等待或正常接手，抢先重验会与在途动作竞争、甚至重复触发受保护操作。
- 某步没有只读终态面（远端不可达、状态面不暴露 generation/verify）：无法旁证完成，必须走原管道执行。
- 存在不可幂等观测的外部副作用（通知已发、配额已扣、不可回滚平台已发布）：目标态相似不证明该步已发生，必须核对该产物本身。
