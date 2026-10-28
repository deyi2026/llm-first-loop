---
method_id: ci-failure-log-first-when-failing-run-matches-local-head-ad031a0d7dae
name: ci-failure-log-first-when-failing-run-matches-local-head
description: CI 门禁红灯通知到达且本地 HEAD 与远端同步时，把『取失败 run 日志』作为第一诊断动作，而非按旧经验先本地复现门禁：失败 run 已在这棵精确树上执行过，其日志直接点名失败段与失败测试。SHA/commit 匹配（gh run list vs git log）是判据；本地只对点名测试窄复现，且用 workflow 点名的命令本体（裸 ruff 的 3121 错是历史债噪音）；修复后走全量本地门禁与审查闸再推送。旧经验『先本地复现』的前置条件是本地/远端分叉或复现性未建立，同步时诊断性重跑属重复执行。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:3f1bb329-18e5-40f1-a208-07928c145a2f:0:912a4b5fc8ee4e226432
evidence_refs: learning:learn:6cacd33a706c
created_at: 2026-10-21T23:00:40.342007+08:00
updated_at: 2026-10-21T23:00:40.342007+08:00
---
## Trigger
收到 push 触发的 CI 门禁失败通知（通知本身即一个已完成、已执行的失败 oracle），本地仓库可访问，且已检索到『先本地复现门禁再修复』类经验卡 tempting 直接进入本地复现

## Discriminator
gh run list 中失败 run 的 commit（SHA 或提交信息）与本地 git log HEAD 完全一致、工作区与远端无分叉 → 该失败 run 已在本地这棵精确树上跑过门禁，失败清单可直接从日志读出，本地诊断性重跑全量/静态段是重复执行；另外 workflow 文件已点名门禁命令本体（如棘轮脚本），本地复现须用命令本体而非裸等价工具

## Short path
- git log -1 / git status 确认本地 HEAD 与远端同步状态（未知量：我在哪棵树）
- gh run list --limit N：用 commit message/SHA 匹配失败 run 与本地 HEAD（未知量：失败是否属于我这棵树）
- 匹配 → gh run view <run-id> --log-failed 过滤 FAILED/error/PASS 摘要行（未知量：哪个门禁段、哪些测试失败）
- 仅对日志点名的失败测试做本地窄复现，用 workflow 点名的命令本体（未知量：本地是否同样失败，排除环境差异）
- 修复 → 本地全量门禁（CI 同款链）+ 仓库审查闸规则 → 推送并定时回查新 run

## Stop conditions
- 失败日志已给出失败测试清单且本地窄复现确认同样失败 → 进入修复，不再做任何诊断性全量/静态段复现
- 失败 run 的 commit 与本地 HEAD 不一致（分叉/落后/他人推送）→ 本方法停用，转旧路径：在精确提交树本地复现门禁
- 日志中无 FAILED 断言行（fail-closed 超时/预算/infra 类失败）→ 按失败类别另行处理，不盲跑本地全量

## Verification
- 本地窄复现的失败测试名与 CI 日志点名完全一致
- 修复推送前本地全量同款门禁链 exit=0（并满足仓库审查闸规则）
- 推送后新 CI run 全绿才收口

## Counterexamples
- 本地与远端分叉（旧经验卡原场景：镜像远端落后 12 提交、本地 main 自身红）——CI 日志属于别的树，必须先在精确提交树本地复现
- 失败是门禁步骤超时/预算 fail-closed 而非断言失败——日志无测试名，应调预算/拆步骤而非读测试
- 无 gh/CI 日志权限或日志已过期——退回本地复现路径
- 失败段是带 base/head 参数的 diff/ratchet 门禁且 CI base ≠ 本地 parent——需先 fetch 算真实差分再本地复现，日志只能定位段别
