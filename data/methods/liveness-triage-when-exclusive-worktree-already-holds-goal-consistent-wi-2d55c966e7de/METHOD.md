---
method_id: liveness-triage-when-exclusive-worktree-already-holds-goal-consistent-wi-2d55c966e7de
name: liveness-triage-when-exclusive-worktree-already-holds-goal-consistent-wip
description: 独占授权的开发任务在指定 worktree 开工时，若任务允许清单内的文件已带与任务目标一致的未提交半成品，第一未知量不是「怎么完成修复」而是「谁在写、还活着吗」：用 diff 目标一致性 + 写入时间线（mtime、最近提交、进程、广播）判定活写者；活写者在场或无法排除时本会话对源文件零写入，转为逐项审读、协调、独立复跑验证与推送收口；只有证据显示写入长期停止才按陈旧残留收编。最终报告必须区分「我做的」与「不是我做的」。
aliases: 开工发现目标文件已被别人改了一半, 任务说我是唯一代理但 worktree 不干净, 半成品 diff 是陈旧残留还是有人在写, 并行会话在同一个分支上写代码我要不要动手, 独占任务现场有未提交修改先查写入者死活
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:87420873-a88f-4fe0-9fcc-3cfe502061f3:0:e2892dfa1899670e1e7a
evidence_refs: learning:learn:3c06ae82fcd9
created_at: 2026-11-13T14:59:01.785832+08:00
updated_at: 2026-11-13T14:59:01.785832+08:00
---
## Trigger
独占开发任务（任务书断言唯一代理、指定 base commit 与分支）开工核查时，git status 显示任务允许文件清单内的目标文件已有未提交修改，且 diff 语义与任务验收项同向（同一缺陷编号、同一校验方向）但未完成（如源码已改、测试未加）。

## Discriminator
任务书的独占断言与现场 dirty 状态矛盾 + diff 内容逐项对应任务目标，两个事实同时成立即把动作空间从「如何实现修复」缩为「判定写入者活性」，并排除并行写入、reset 覆盖、直接冒认三种错误动作。

## Short path
- rev-parse + status 核对 HEAD/分支/dirty 清单与任务书一致（brief 内绝对路径失效时，用机器无关的 worktree 叶名在本地重定位根，如 pwd + ls .worktrees）
- 通读 dirty diff，逐项对照任务验收清单判定目标一致性与完成度
- 建立写入时间线（文件 mtime、最近提交时刻、可用进程/广播通道），判定活写者 vs 陈旧残留
- 活写者成立或无法排除 → 本会话对源文件零写入，转入审读 + 协调 + 独立验证角色
- 独立复跑定向 pytest/lint/类型检查/diff-check，以回执为准核对提交信息里的自报统计
- 走推送流程；push 前置闸若在任务授权范围外失败（如主工作区知识资产待入库），按任务书停手并交接，不绕闸不改闸

## Stop conditions
- 活写者的提交已覆盖验收清单且独立验证全绿 → 不重复实现，只收口验证与推送流程
- push 前置闸失败点在任务授权范围外 → 停止并报告，不修改闸所指向的工作区
- 写入者身份无法确证（沙箱阻止进程检查等）→ 报告中显式标注不确定性，既不冒认贡献也不武断指认

## Verification
- 独立运行定向测试/lint/类型检查与 diff-check，回执为准，不采信并行写入者 commit message 中的自报数字
- 最终报告区分本会话实际动作与并行写入者产出，并列残余风险（push 待办、写入者可能复活等）

## Counterexamples
- dirty 修改与任务目标无关（其他 lane 的越界改动）→ 本方法不适用，应上报/停手而非审读收编
- mtime、进程、广播证据显示写入已停止很久且无活动进程 → 属陈旧残留，走 resume 状态对账或收编提交路径接管
- 任务书明示「接手/清理在途现场」→ 已被授权接管，直接评估残留质量而非等待活写者
