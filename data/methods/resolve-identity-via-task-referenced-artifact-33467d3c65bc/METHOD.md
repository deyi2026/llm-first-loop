---
method_id: resolve-identity-via-task-referenced-artifact-33467d3c65bc
name: resolve-identity-via-task-referenced-artifact
description: 恢复中断任务时，若会话 Evidence 未命中，但任务计划自身引用了与目标标识符绑定的具体工件（如以 PR 号命名的临时 worktree），先读该工件的 git 元数据（.git 指针/remote）一跳恢复 owner/repo，再以'编号+标题/分支语义'双重匹配向服务端查询；不要对家目录全枚举并逐仓库裸查编号（编号会碰撞）。网络慢时用服务端 compare API 替代本地 fetch。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:1089:e0e13aaa06073fe56037
evidence_refs: learning:learn:c0b8dfb3f3fc
created_at: 2026-09-18T05:23:42.943691+00:00
updated_at: 2026-09-18T05:23:42.943691+00:00
---
## Trigger
跨会话恢复多步任务：search_evidence 未命中目标的 owner/scope（如 PR #28 属于哪个仓库），但计划文本自身引用了与目标标识符绑定的工件（临时 worktree、以其命名的分支/目录），该工件按定义是目标对象的检出/载体

## Discriminator
开场计划已写明'清理临时 worktree'，且工件名与目标编号绑定（lfl-pr28-fix ↔ PR #28）：worktree 必然属于目标仓库，其 .git 指针 + git remote -v 一跳即得 owner/repo，并携带分支语义可识别编号碰撞（SYAGI #28 是另一个 PR）。此事实在第一次工具调用前已存在，本可把'N 个候选仓库'缩成'一个可验证下一跳'

## Short path
- search_evidence 查 PR #28 上下文 → 未命中 ⇒ 当前未知量=目标所在 owner/repo
- 读计划引用工件的元数据：cat /private/tmp/lfl-pr28-fix/.git 得 gitdir 指向主镜像，git remote -v 得目标 remote ⇒ 直接获得 owner/repo
- gh pr view 28 -R <owner/repo>，用编号+标题/分支语义双重确认是同一对象（headRefName=integration/main-convergence）⇒ state/mergeable/CI 一次核验
- 本地 fetch 超时则改服务端 compare API（ahead_by/behind_by）验证基线漂移，不阻塞在本地网络
- gh pr merge --merge 后核验 state=MERGED、mergeCommit==main tip
- 对 merge commit 查 main CI 结果、确认 worktree 干净后移除；三步均有权威回执即停止

## Stop conditions
- 工件元数据得到的 owner/repo 与服务端返回的标题/分支语义一致（编号+语义双匹配），此后不再枚举其他仓库或目录
- 计划的合并、main CI 确认、worktree 清理三步均被权威回执验证完成

## Verification
- gh pr view 返回的 headRefName/标题与任务所述主题一致，而非仅 number 相等（防编号碰撞误认）
- worktree 的 gitdir/remote 与最终查询的仓库一致；merge 后 main tip == mergeCommit；CI 回执 head 为 merge commit

## Counterexamples
- 计划未引用任何绑定目标的工件（无专属 worktree/分支/目录）→ 宽发现或询问用户才是正解，本方法不适用
- 引用的工件已删除/prunable 或命名只是巧合属另一任务 → 指针必须先经服务端语义校验，否则回退宽发现
- search_evidence 命中且直接给出 owner/repo → 工件跳板多余，应一步直查
