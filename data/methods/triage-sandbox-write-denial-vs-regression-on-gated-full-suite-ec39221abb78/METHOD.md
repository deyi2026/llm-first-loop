---
method_id: triage-sandbox-write-denial-vs-regression-on-gated-full-suite-ec39221abb78
name: triage-sandbox-write-denial-vs-regression-on-gated-full-suite
description: 沙箱执行面（启动回执已声明受限写面）里跑全量 CI/测试门禁失败、出现『未登记新红』时，先按失败帧分类：setup/fixture 中外部命令因写权限被拒（Operation not permitted / exit 128，路径在声明写面外）→ 环境性失败，用同类路径的无关命令独立复现确认；候选断言失败 → 按回归处理。漂移核验分两层：staged 须与冻结集逐项一致，unstaged 新增按是否测试运行产物分类（≠源码漂移但如实上报）。不登记新红、不旁路、不降级重试，裁决权交用户。
aliases: 沙箱跑CI新红怎么判断是环境问题, 测试setup git权限被拒算回归吗, Operation not permitted 测试失败归类, 门禁失败环境性还是代码问题, 全量测试跑完工作区多出文件算漂移吗
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:10609991-e7ca-4066-a5ef-6119768bd036:6:6caa8324bfede0de9037
evidence_refs: learning:learn:84ed25e7f1b8
created_at: 2026-10-25T23:44:28.172252+08:00
updated_at: 2026-10-25T23:44:28.172252+08:00
---
## Trigger
通过沙箱化执行工具（回执明示受限写面，如 sandbox-exec 仅允许写工作区与缓存目录）运行全量 CI 门禁/测试套件，终态 exit≠0，且红数对账或测试报告出现未登记新红/意外失败，同时任务要求事后核验工作树未漂移。

## Discriminator
两条当时已在手的事实：①启动回执明示允许写的范围，且候选常是 linked worktree（.git/gitdir 位于工作区外）；②逐条新红的 traceback 显示失败点在测试 setup/fixture 执行外部命令（如 git worktree add）时以文件系统写权限错误退出（Operation not permitted / exit 128），目标路径在声明写面之外——这是环境性失败的判别信号，区别于对候选代码的断言失败。

## Short path
- 派发长任务时即记录：回执声明的沙箱写面 + 候选 git 拓扑（是否 linked worktree、gitdir 是否在工作区外），据此预判哪些门禁步骤与事后核验命令（write-tree、status 刷新 index）会被拒。
- 失败后从全量输出逐条定位新红的失败帧类别：setup 权限拒绝 vs 候选断言失败。
- 对权限类新红，用一条与该测试无关的命令触及同类路径，独立复现同一拒绝（如 git 建索引锁被拒 exit 128），确认为沙箱环境性而非源码回归。
- 漂移核验分两层：staged 集合与冻结清单逐文件核对（数量+路径+A/M 状态码）；unstaged 新增按是否测试运行产物（如 reports/**）分类，判为副作用并如实列出，不混同源码漂移。
- 停止推进：不登记新红、不改红台账、不重试或降级（如 --quick）；把裁决选项（放宽沙箱重跑 / 登记环境红 / 还原产物文件）连同证据清单交用户。

## Stop conditions
- 每条新红均已归为『环境性（已有独立复现）』或『候选可疑（断言失败）』，且漂移分层结论（staged 一致性、unstaged 产物清单）已出具。
- staged 集合与冻结清单不一致，或 unstaged 出现非测试产物的源码修改 → 判真实漂移，立即停止并上报。
- 沙箱内无法完成的核验（如 tree hash）如实标注『未能复验』，不得伪造、猜测或静默跳过。

## Verification
- 用不同命令在同类路径上复现同一权限拒绝（exit 128 / Operation not permitted），证明失败属写面约束而非候选行为。
- staged 文件清单与冻结清单逐项比对（文件数、路径、状态码）完全一致。

## Counterexamples
- 新红是关于候选代码行为的断言失败（非 setup 权限错误）→ 按源码回归处理，不得借沙箱开脱。
- 门禁运行在无沙箱或写面覆盖全部被写路径（含 gitdir）的环境 → 权限判别不成立，失败直接按回归排查。
- 沙箱未隔离网络时的网络类失败，不属写面判别范围。
- 测试套件不产生副作用产物且 unstaged 全是源码文件 → 直接按真实漂移停止，不做产物分类。
