---
method_id: patch-equivalence-first-close-or-deliver-for-stale-branches-a16e3f4e387f
name: patch-equivalence-first-close-or-deliver-for-stale-branches
description: 本地功能分支基于旧 main、且 fetch 显示近期有 sync/bulk-merge 型 PR（如 repo-sync）落地时，先用 per-commit patch 等价判定分支内容是否已被捎带上游化，再决定是否进入交付管线。判据：git cherry 全 '-' 且本地 commit 与上游孪生 commit 的 git patch-id 相等 → 无需 rebase/测试/push/PR，直接关项并清理冗余 worktree；任何 diffstat 都不是判据（merge-base diffstat 恒非空，两点 diff 混入 main 后续演进的树漂移伪影）。仅对含 '+' commit 的分支投入真实工作，用路径限定 src diff 评审可摘取性与冲突面。一次便宜的 cherry 扫描即可把全部待办分支分成'已闭合'与'唯一需做'两类。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:32d694c9-dbcd-4dc8-a941-0885c617868c:595:dfd200655beda86f75b8
evidence_refs: learning:learn:271321cb4577
created_at: 2026-09-19T23:14:11.150672+00:00
updated_at: 2026-09-19T23:14:11.150672+00:00
---
## Trigger
待交付的本地功能分支基于旧 main，且 fetch 后可见 main 头部新增 sync/bulk-merge PR 的 merge commit（分支 commit 可能被捎带上游化）；或 rebase 输出 skippedCherryPicks 提示/落位后 diff 为空

## Discriminator
一条 `git cherry <upstream> <branch>` 输出：全部 commit 标 '-' 即 patch 等价已上游化；再以 `git log <upstream> --grep <subject>` 定位孪生 commit 并比对 `git patch-id` 相等即闭环。对 main 的 diffstat（两点或三点）不构成判据：merge-base diffstat 必然非空，两点 diff 含 main 后续新增/删除造成的树漂移伪影（如 -58k/-49k 行）

## Short path
- fetch 后看 main 新增 merge commit：未知量=近期 sync PR 是否可能捎带本地分支 commit
- 对每个待交付分支先跑 `git cherry <upstream> <branch>`（先于 rebase/测试/push）：未知量=是否存在 patch 级未上游化 commit
- 全 '-' → 用 commit subject 在 upstream log 搜孪生 commit 并比对 `git patch-id`：未知量=上游 commit 是否内容等价
- patch-id 相等 → 该分支判'无需 PR'，删除冗余 worktree，跳过测试环境修复与 push/PR 动作
- 出现 '+' commit 的分支才是真实工作：用路径限定 src diff（而非全树 diffstat）评审是否与 upstream 已上线面冲突、能否只摘独立增益部分
- 用同一 cherry 检查横扫其余待办分支，全部分类为 closed / needs-extraction 后停止

## Stop conditions
- 某分支 cherry 全 '-' 且 patch-id 与上游孪生 commit 相等：立即终止该分支的一切交付动作，仅做冗余 worktree 清理
- 全部待办分支完成'已闭合/需提取'二分类，仅剩 '+' 集合进入评审

## Verification
- 本地 commit 的 git patch-id == 上游孪生 commit 的 patch-id，且 commit subject 一致
- git cherry 输出中无 '+'；对 '+' 分支的提取/重放结论必须引用路径限定 src diff
- 若仅 subject 相同而 patch-id 不同，视为分叉实现，退回内容级 diff 评审，不得判等价

## Counterexamples
- git cherry 出现 '+' commit（如 73-commit 的耦合工具面重构分支）：内容确未上游化，必须走正常评审/提取管线，不能因同主题 commit 曾在 main 出现就关闭
- main 无新 merge 且分支不落后：预检是纯开销，直接按常规 rebase→test→PR 交付
- 待处置对象是 worktree 内未提交/未跟踪脏文件或已被系统清理的 /tmp worktree：patch 等价判据完全不适用，需另行恢复/归档
- 目标是判断分支与 upstream 已上线语义是否冲突（patch 等价只回答'内容是否在 main'）：仍需读 src diff 决定只摘独立增益还是放弃重放
