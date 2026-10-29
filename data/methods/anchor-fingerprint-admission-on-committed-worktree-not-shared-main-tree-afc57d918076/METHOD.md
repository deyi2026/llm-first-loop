---
method_id: anchor-fingerprint-admission-on-committed-worktree-not-shared-main-tree-afc57d918076
name: anchor-fingerprint-admission-on-committed-worktree-not-shared-main-tree
description: 多会话共享主工作区的仓库里，把绑定产物指纹的审查/门禁准入冻结在主工作区快照上，任何并发会话的写入（哪怕只是别的任务改一个 docs 文件或新增未跟踪产物）都会让执行时被判『快照不匹配/无覆盖资格』。改动一旦已成 commit，就应把准入锚定到不可变 SHA：用 git worktree add --detach <sha> 得到零脏检出，在其中冻结审查并跑门禁链。收到快照不匹配拒绝时一次性改锚重入，不在可变主树上反复重冻结碰运气。门禁红且红点不在本 commit 文件时，在同一 worktree 对父提交跑同一门禁脚本实测归因存量/新增，再定修复归属，不据此虚报完成。
aliases: 审查准入被并发改动作废, 快照不匹配无覆盖资格怎么办, 多会话共用工作区怎么过审查, 干净 worktree 跑门禁准入, 冻结审查指纹选 commit 还是工作区
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:505:98790e0169a1b2a1d901
evidence_refs: learning:learn:60cc6a872c94
created_at: 2026-10-28T22:06:24.481267+08:00
updated_at: 2026-10-28T22:06:24.481267+08:00
---
## Trigger
指纹绑定审查回执/门禁准入即将冻结，且 (a) 仓库主工作区由多会话共享——status 已显示其他任务的未跟踪/修改产物，(b) 待验证改动已（或按流程应先）成为独立 commit。

## Discriminator
准入机制快照的是整棵工作树（含与任务无关的未跟踪文件），而待验证产物已有不可变 commit SHA，且审查规则文本本身声明『产物变化→回执失效』。两者并存时：主树锚点漂移只是时间问题，commit 锚点漂移概率为零——第一次冻结就应选后者，而不是等被拒后再补救。

## Short path
- git status/diff 界定本任务文件集合；确认主树上混有其他会话/任务的未跟踪与修改产物（漂移风险信号）。
- 先把本任务改动提交为独立分支上的 commit，制造不可变指纹。
- git worktree add --detach <commit-sha> 建零脏检出，在其中冻结审查准入并执行门禁链——并发写无法触碰该快照。
- 若执行仍报快照不匹配：一次性改锚到 commit SHA 重入；不重复冻结主树碰运气。
- 门禁 BLOCK 且红点不在本 commit 文件：同一 worktree 检出父提交，跑完全相同的门禁脚本归因存量 vs 新增，据此定修复归属线与状态标注（红门不声称完成）。
- 准入结束删除临时 worktree，确认回执指纹与 commit 对应。

## Stop conditions
- 审查/门禁回执的 candidate 指纹即目标 commit 的干净检出，verdict 已落盘；
- 红点已实测归因（父提交同样红=存量债务）并已决定归属（另开修复线 or 阻断不推），任务状态如实标注。

## Verification
- 准入发起前 worktree 内 git status 必须为空（零修改、零未跟踪）；
- 回执 candidate 指纹对应 commit 检出而非主工作区；
- 归因运行使用与门禁完全相同的脚本与参数（同 ratchet、同口径），不目测不推测。

## Counterexamples
- 审查按设计发生在提交前（产物就是工作树状态）：只能冻结主树，应在无并发写窗口进行或接受窄复审成本。
- 单会话仓库、无人并发写主树：直接冻结主树即可，worktree 只是额外开销。
- 准入机制原生按 commit SHA 绑定：直接传 SHA，无需 worktree。
- 无关未跟踪文件已被 gitignore 排除出指纹、且无会话修改 tracked 文件：漂移风险可忽略。
