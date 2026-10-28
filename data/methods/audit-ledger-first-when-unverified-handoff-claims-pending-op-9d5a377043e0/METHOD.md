---
method_id: audit-ledger-first-when-unverified-handoff-claims-pending-op-9d5a377043e0
name: audit-ledger-first-when-unverified-handoff-claims-pending-op
description: 跨会话接管的状态快照声称某个有状态大操作（数据迁移/目录切换/停机窗口作业）『未做、待执行』，而状态恢复回执本身标 semantic_verified=false 或 applies_to_current_run=false（或快照自述部分事实已过时）时，第一个未知量不是『怎么执行』而是『是否早已执行』。此类操作通常自带 append-only 审计台账（按操作类+时间戳落盘，backup/rehearse/migrate/verify 链）与只读 verify 子命令：先查台账最新记录、跑 verify，把『待执行』翻转成『已完成+残余清理』或『确实未做』，再决定后续。快照是过程观察，操作自有台账才是真值。与『对外动作重做前读权威完成证据』互补：这里证据源是本地操作自带审计与 verify，触发源是带未验证标记的机器回执。
aliases: 快照说没做先查审计台账再做, 接管任务先确认是不是早就干完了, 迁移动手前先跑一遍verify, 状态恢复说待执行其实已执行完, 别信接力快照的未做结论
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:dde2bfc3-0cb0-4295-beeb-ebfc5ea079d2:35:78040a066c8a2591dff5
evidence_refs: learning:learn:bdc7793e9b29
created_at: 2026-10-26T12:50:17.315397+08:00
updated_at: 2026-10-26T12:50:17.315397+08:00
---
## Trigger
接手跨会话/接力任务时，恢复的状态快照断言某有状态大操作（迁移、cutover、停机作业）『未做』，且满足任一：回执带 semantic_verified=false / applies_to_current_run=false；快照自述其中事实『已过时、后续已推进』；或该操作类在仓库内已知有审计台账与 verify 工具。

## Discriminator
动手规划执行前就已可见的三件事：①状态回执的机器校验标记（未验证/不适用当前 run）；②快照内部自认过时；③该操作类存在 data/audit/<操作类>/<时间戳>.json 式 append-only 台账与只读 verify。这三件事足以把『如何执行』缩成『是否已执行』一个未知量。

## Short path
- 读状态恢复回执的校验标记；未知量：快照的『未做』断言可信吗？
- 标记未验证或自述过时 → 把第一未知量改为『该操作是否已执行』：定位该操作类自有审计台账，读最新时间戳记录（backup/rehearse/migrate/verify 链）；
- 台账显示已执行 → 跑只读 verify（或读最新 verify 报告）拿权威当前态，按失败签名分流：迁移后正常增量 vs 真实残留；
- 台账缺失或记录为失败/中断 → 才按快照细节进入执行规划（或幂等续跑/回滚分支）；
- 判定由台账+verify 权威确认后停止发现，转入残余处置。

## Stop conditions
- 台账最新记录晚于快照生成时间且为 PASS/完成，且 verify 失败项全部归类为非丢失 → 不再按『未做』规划，任务转为残余清理；
- 台账确实缺失且目录/存在性探针证实目标状态未达成 → 才按快照进入执行流程。

## Verification
- 台账最新记录时间戳与步骤结果（precheck→migrate→switch）构成完整链且晚于快照；
- 只读 verify 每个失败项可逐条解释（正常增量/真实残留），无数据丢失签名；
- 残余项处置后再跑一次 verify 确认清零。

## Counterexamples
- 操作类没有自带审计台账或 verify 工具 → 不能翻台账，改为直接幂等存在性探针/dry-run 判定当前态；
- 快照回执 semantic_verified=true 且时间戳覆盖该操作之后 → 断言可信，直接进入执行规划；
- 用户在场且能即时确认窗口与状态 → 优先问用户，先于翻台账；
- 台账显示操作失败中断 → 不是已做/未做二值，按幂等设计走续跑或回滚分支，而非当作未做重头规划。
