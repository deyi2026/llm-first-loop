---
method_id: snapshot-cwd-recovery-and-artifact-freshness-liveness-after-restart-80371e80f4b9
name: snapshot-cwd-recovery-and-artifact-freshness-liveness-after-restart
description: 会话重启后恢复长跑批任务时，先前状态里的相对产物路径在当前 cwd 失效、后台 durable job 查询只回 orphaned 且无输出：第一步不是枚举主仓/镜像/worktree 候选根，而是水合恢复态自带的 source_refs（或活跃窗口最新一条命令快照），其命令文本内嵌绝对 cwd（cd 前缀/日志头路径），一次命中产物根；随后用进度计数+mtime 新鲜度对每个 orphaned 职责分别裁决死活（同批可一活一死），活任务挂定时器等终态文件、死监视器直接接管。orphaned 只代表句柄丢失，不代表进程死亡，禁止据此重启长任务。
aliases: 重启后找不到跑批输出目录, 后台任务句柄丢了怎么判死活, 恢复会话时相对路径读不到先查命令快照, 跑批产物落在哪个 worktree, checkpoint 还在涨就别重跑
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:89aa4eb4-d3e8-4612-9858-cce4b0fe5b6d:2228:98345fa478908c84e03a
evidence_refs: learning:learn:d985cf9b5543
created_at: 2026-10-26T21:35:54.299042+08:00
updated_at: 2026-10-26T21:35:54.299042+08:00
---
## Trigger
会话/进程重启后恢复任务：先前状态记录的相对产物路径在当前 cwd 下读取失败（或按状态里的路径找不到目录），同时后台 durable job 查询返回 orphaned/无本地句柄/无输出，需要定位先前会话实际写入的产物根并判断各后台作业是否还活着。

## Discriminator
恢复态的 source_refs 与证据索引中活跃窗口（最后一次已知活动时段）的 execute_command 快照当时已在手：这些快照的命令文本天然内嵌绝对 cwd（cd 前缀、日志头的工作树路径），是无需猜测的权威路径来源。另一条判别事实：job 状态=orphaned 仅说明本地句柄丢失，落盘产物的行数-vs-目标数与 mtime 新鲜度才是活性真值（同批两个 orphaned job 可得出相反裁决）。

## Short path
- 读恢复态，列出待解未知量：作业终态、自动收尾产物、产物实际根在哪
- 查 durable job 句柄；回执 orphaned 且 0 行输出 → 未知量转为『产物实际在哪、进程是否真死』
- 水合恢复态 source_refs（或活跃窗口最新一条命令快照）的前几百字符，从命令文本读出先前会话的绝对 cwd
- 在该根下枚举产物目录：checkpoint 行数 vs 目标总数、checkpoint/run.log 的 mtime、预期终态文件（report.json 等）是否已出现
- 按新鲜度分别裁决各 orphaned 职责：仍在推进→挂定时器等终态文件后接管收尾；停止推进（如 watch.log 只剩 start 行）→判定已死，本会话直接接管其职责
- 把产物绝对根、活性裁决与接管计划写入新状态，防止再次重启重复定位

## Stop conditions
- 已取得产物绝对根，且对每个后台职责（作业/监视器）得到独立的死活裁决并落实了对应动作（等待定时器或接管）
- 快照水合后命令文本不含任何绝对路径线索，才升级到 worktree/镜像候选枚举或向用户求证

## Verification
- 快照读出的 cwd 与产物目录存在性互证：ls 该根成功，且 checkpoint/日志/预期产物确实落在其下
- 活性裁决与后续观察一致：判活的作业 mtime 持续推进、终态文件按 ETA 出现；判死的无任何新写入

## Counterexamples
- 恢复态记录的本就是绝对路径且直接可读 → 直接消费产物，不必绕道水合快照
- job 查询返回明确终态（completed/failed 且附输出）→ 直接读输出，无需路径恢复与活性裁决
- 先前会话工作在临时/容器目录且已随环境销毁 → 快照 cwd 不可信，应重新发现或问用户
- 快照是 telemetry/检索类证据、命令文本不含 cwd → 本判别不适用，回到常规发现流程
