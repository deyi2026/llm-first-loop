---
method_id: stale-plan-item-adjudication-via-baseline-commit-delta-0c2bf2751527
name: stale-plan-item-adjudication-via-baseline-commit-delta
description: 接续上轮移交的多项计划（交付物均为可入库工件）时，若锚点检查发现现状与计划陈述不符（HEAD 前移、声称的未跟踪/暂存条目消失），先跑有界区间 git log <计划基线>..HEAD，而不是先重搜 evidence 或横向扩查 worktree/兄弟目录：中间提交的 subject 常直接点名已落地的计划项（如「入库 N 张方法卡」）。据此把每项三分类：外部已完成→引用 commit 跳过不重做并标注非本 run 完成；前提形式失效但需求仍在（如工作树干净但基线内容过期）→用该域权威 checker 重推真实状态；仍待办→执行。消失的工件先当「可能已被区间内提交收编」，不进「去别处找」分支。用一段有界时间差替代空间枚举，一次问清「哪些还要做」。
aliases: 执行上轮计划前提对不上 先查新旧HEAD区间提交, 待办清单里的事项可能已被别的会话做完, 计划说的未跟踪文件不见了 先git log还是先找worktree, 接续跨会话任务先裁决哪些P项已落地, 别人已替我提交 不重做 认领commit证据
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:ccfcc676-9c54-41d9-8c5c-5dab5ce0e5b2:1320:2a5a3e23edc652de6142
evidence_refs: learning:learn:acab9c3def50
created_at: 2026-11-10T10:42:41.141749+08:00
updated_at: 2026-11-10T10:42:41.141749+08:00
---
## Trigger
接续上一轮/上一会话移交的多项计划（各项交付物为可入库工件：提交、清单更新、脚本守卫等）开始执行，且计划上下文存有旧基线 ref（如上轮 HEAD）；首个锚点检查（toplevel/HEAD/status）显示现状与计划陈述不符——HEAD 已前移、计划声称存在的未跟踪或暂存条目消失。

## Discriminator
锚点输出中当前 HEAD ≠ 计划基线 ref，这一事实本身就蕴含一个有界区间 <基线>..HEAD：其间的 commit subject 是「计划写成后外部落了什么」的权威记录，常逐字对应计划项交付物。发现漂移那一刻即可用，无需先恢复上轮 evidence、也无需枚举 worktree/兄弟仓库去定位「消失的工件」。

## Short path
- 锚点检查 toplevel+HEAD+status，与计划陈述逐项比对；不符即宣告漂移，不按旧结论继续。
- 先跑有界区间 git log --oneline <计划基线>..HEAD（必要时 --stat）：未知量=计划写成后外部落了什么；在区间解释漂移之前，禁止重搜上轮 evidence 或横向扩查 worktree/兄弟目录。
- 把区间提交映射回各计划项做三分类：已落地→记 commit 为证、跳过不重做并显式标注「非本 run 完成」；前提形式失效但需求仍在（如 manifest 工作树干净但基线内容过期）→用该域权威 checker（diff 校验/审批脚本）重推真实状态再决定；仍待办→按原计划执行。
- 逐项汇报 provenance（本 run 完成 / 外部完成+commit / 重推导 / 待办）；消失的工件一律先按「可能已被区间内提交收编」处理，只有区间证伪后才进入空间搜索分支。

## Stop conditions
- 所有计划项均已对当前权威状态裁决完毕并绑定证据（具体 commit hash、空 diff 实证或权威 checker 输出）。
- 计划无基线 ref、或为本 run 刚制定（无中间写者可能）、或交付物不在 git 历史观测面——停用区间裁决，改走运行时/provenance 面或直接执行。

## Verification
- 「已完成」结论必须绑定具体 commit 并用 git show --stat 复核一次，或以 diff 为空实证，不接受仅凭条目消失推断。
- 「前提失效」项须用权威工具重跑确认（如漂移计数 42/42→0 的实测输出），再裁决是否仍需执行。

## Counterexamples
- 计划是本 run 刚写的、无中间写者可能：区间查询是纯开销，直接执行即可。
- 交付物不在 git 历史观测面（外部服务配置、线上审批、部署状态）：commit 区间不裁决，须查运行时/部署记录。
- 区间含数百条合并列车提交、subject 无法映射计划项：退化为按工件路径的 scoped log 或逐项状态检查，区间法失效。
