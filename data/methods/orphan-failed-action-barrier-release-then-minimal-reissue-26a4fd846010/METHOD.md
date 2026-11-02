---
method_id: orphan-failed-action-barrier-release-then-minimal-reissue-26a4fd846010
name: orphan-failed-action-barrier-release-then-minimal-reissue
description: 受管服务控制面出现 admission_barrier/orphan_barrier 且持有者是上一轮终态 failed 的动作时：按回执点名的 operation_id 读动作记录，确认『程序不自动重跑、待裁决』且效果确实缺失（live git_head≠desired）后，用控制面自带出口 release 释放陈旧屏障，再只对受阻目标重发最小动作，按点名 action_id 核验收敛；不深挖运行时源码重推屏障机制、不清扫并发写者旧经验、不重复轮询持有者未变的 status。
aliases: 重启卡在上一轮失败动作上怎么解, orphan barrier 挡住服务先放行再重启, failed 动作占屏不自动重跑, 准入屏障遗留导致重启不生效, wecom 重启不生效被旧动作拦住, terminal barrier 处置顺序
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc422278-b7a4-4c97-9380-4dc56a6da24f:6424:c0a0c3f200fa9e4d4a9b
evidence_refs: learning:learn:c7199c5347f6
created_at: 2026-11-02T10:47:05.128680+08:00
updated_at: 2026-11-02T10:47:05.128680+08:00
---
## Trigger
status 显示某服务 live≠desired（用户声称的『已重启』对该服务不成立），且 admission_barrier/orphan_barrier 点名一个历史 operation_id（reason=restart、corrupt=false）

## Discriminator
回执三处点名事实同时成立：①屏障记录给出 operation_id+service；②按该 id 读到的动作记录 status=failed 且 detail 明确『程序不自动重跑，待模型/新动作裁决』；③该服务 live git_head≠desired（效果真缺失，非归因伪影）。三者齐备即『死持有者屏障』，出口就是控制面自带的 release，区别于活跃 run 持有（等待/外部执行）与并发成功伪影（acknowledge 归因）

## Short path
- status 按服务视图：找出哪个服务 live≠desired、屏障点名的 operation_id——未知量：谁在挡
- 按点名 operation_id 读动作记录：确认 status=failed、『不自动重跑，待裁决』、且该服务效果确实缺失——未知量：持有者是死动作还是活跃 run
- 从控制面自身取出口菜单（receipt hint 的 view=full，或单点 grep available_exits 得 release|adopt|override），死持有者选 release
- service_control(release, service=<受阻目标>)：回执 previous_owner 应等于屏障 operation_id，防误放他人活跃屏障
- 只对受阻目标重发最小动作（单目标而非 all），从受理回执拿点名 action_id 与核验入口
- 按点名入口 status(action_id) 断言 succeeded 且 live.git_head==desired，屏障列表清空，停止

## Stop conditions
- release 回执 previous_owner==屏障 operation_id，且重发动作 status=succeeded、live.git_head==desired，orphan_barrier 不再含该服务
- 动作记录显示持有者是活跃 requester/run，或失败目标已被时间窗内并发 succeeded 动作覆盖（live 已==desired）→ 停止本分支，转有界等待/外部执行者/acknowledge 归因

## Verification
- service_control(action=status, action_id=<重发动作id>) 断言 succeeded 且 convergence.lagging 不再含该服务
- 复查服务视图：admission_barriers/orphan_barrier 不再出现该服务
- release 回执的 previous_owner 与屏障 operation_id 一致

## Counterexamples
- 屏障在等活跃 requester/run 退出且持有者就是目标进程自己：release 会击穿保护在途运行的闸，应转外部执行者路径
- 唯一失败目标是并发竞争归因伪影且 live.git_head 已==desired：效果已达成，只需 acknowledge 闭合记录，不 release 不重发
- barrier corrupt=true 或出口菜单不含 release：按 view=full 的 gate_classification 走 override/adopt 并附证据等级，而非盲 release
- 四服务全部 live==desired 且无屏障：『已重启』为真，无需屏障处置，直接执行任务本体
