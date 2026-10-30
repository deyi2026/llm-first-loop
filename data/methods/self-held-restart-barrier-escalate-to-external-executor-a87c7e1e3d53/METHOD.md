---
method_id: self-held-restart-barrier-escalate-to-external-executor-a87c7e1e3d53
name: self-held-restart-barrier-escalate-to-external-executor
description: 服务重启终态 failed 且原因是准入屏障在『等待某个活跃 requester/run 退出』时，决定处置路径的不是更多状态轮询，而是屏障持有者的身份：读 reason 文件拿到 gate 语义，再读 inflight/审计记录的 created_by 标识，与目标服务的 live pid 比对。若持有者就是待重启进程自己（或其托管的运行），等待与重试在结构上不可能解除——拒绝记录会按时间重复出现——唯一可行路径是由非目标托管的执行者（外部会话或用户手动）发起重启；此时应停止轮询、把该决定呈报用户。若持有者是其他会自然结束的任务，则有界等待后复查一次即可。
aliases: 重启卡在等 requester 退出一直不解除, 服务自己挡住自己的重启, 谁持有重启屏障怎么查, self-restart deadlock 需要外部执行, 从服务进程内部发起重启失败
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:f02d0f78-2dee-4e98-8056-26c7c3042ab0:63:867d647b9dc55152bbc3
evidence_refs: learning:learn:1be14c19eb58
created_at: 2026-10-30T19:27:35.565543+08:00
updated_at: 2026-10-30T19:27:35.565543+08:00
---
## Trigger
restart 类异步服务动作终态 failed，失败原因不是崩溃或配置校验错，而是准入屏障在等待某个活跃 requester/run 退出（如 waiting_for_requester_exit、barrier protecting active run）。

## Discriminator
屏障持有者的持久化审计记录（inflight/audit 的 created_by pid 或 session 标识）与 status 回执里待重启服务的 live 进程是同一个——被重启者自己持有屏障；配合拒绝记录时间线重复出现同一条，即可判定等待在结构上永远无法解除，而非一次性竞态。

## Short path
- 从 failed 回执取 action_id 与 reason_ref，直读 reason 文件；未知量：卡在哪类门、在等谁退出。
- 若属 requester-exit 类屏障，读 inflight/owner 审计记录；未知量：持有者身份。
- 把持有者 pid/session 与目标服务的 live pid 比对；未知量：等待是否有意义。相同即判『等待无效』，不再重刷同一聚合 status 面（其失败详情会被 generation_lag 类审计噪声挤出截断区，应按 action_id 从已持久化回执/证据定位）。
- 上报唯一可行路径：重启必须由非目标托管的执行者（外部会话或用户手动）发起；该决定涉及对 live 的实质变更，呈报用户而不自行代选。
- 若持有者是其他确会自然结束的活跃任务，则转入有界等待后复查一次，不升级。

## Stop conditions
- 持有者身份已与目标进程对齐钉死，且『外部执行/用户手动』作为必要前提已呈报决策；
- 或确认持有者为独立、会结束的请求，已转入有界等待并定好复查点。

## Verification
- inflight/审计的 created_by pid 与 status 中目标服务的 live pid 完全一致；
- service_admission_rejections（或同类拒绝流水）显示同一条拒绝在时间线上重复出现，佐证结构性而非瞬态。

## Counterexamples
- 屏障持有者是另一个确实会自然结束的活跃任务/会话（如正在收尾的 run）→ 有界等待加复查即可，不必升级外部执行；
- failed 根因是配置/校验错误或发布快照缺失，无屏障语义 → 修配置或补快照，追究『谁持有』无意义；
- 目标服务计划内即将退出（scheduled exit）→ 短暂等待后原路径重启可能直接成功。
