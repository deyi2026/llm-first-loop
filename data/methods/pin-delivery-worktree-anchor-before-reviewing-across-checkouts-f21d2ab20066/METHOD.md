---
method_id: pin-delivery-worktree-anchor-before-reviewing-across-checkouts-f21d2ab20066
name: pin-delivery-worktree-anchor-before-reviewing-across-checkouts
description: 多 worktree 仓库的只读审查任务以 commit tip 指定交付范围时，若 cwd 的 rev-parse 显示 HEAD 不等于该 tip，第一未知量不是『cwd 为什么脏』而是『交付物物理在哪个 checkout』。先一次 worktree list 定位 HEAD==tip 的交付 worktree，并在读内容或枚举脏文件前验证其 HEAD、tree 指纹与 porcelain 清洁度；cwd（镜像 main）的脏清单只作范围外澄清，一行计数加类别即可。终局裁决里任何工作树状态断言（清洁度、树内运行时证据）必须出自锚点验证之后。
aliases: 审查前先确认在哪个worktree, HEAD对不上先找交付分支检出目录, 多worktree仓库别把镜像main当交付树, 镜像仓脏文件不算交付候选, 补审先钉交付worktree指纹和清洁度
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:68f988f8-815b-4893-97c4-1a2da8a387f3:156:bcfd3f8addd2690de4a7
evidence_refs: learning:learn:d325f083516e
created_at: 2026-11-14T09:07:14.070662+08:00
updated_at: 2026-11-14T09:07:14.070662+08:00
---
## Trigger
审查/审计/补审任务点名交付 commit SHA 或分支 tip（常附 tree 指纹与 ahead 计数），而 shell cwd 的 git rev-parse 或 status 输出显示当前检出是另一分支/镜像且带脏文件——仓库存在多个 lane worktree。

## Discriminator
首次 rev-parse 批查输出即可见三值对拍：cwd HEAD ≠ 任务点名 tip，且基准（如 origin/main）另有其值；随后 worktree list 一行即给出 HEAD==tip 的专属 worktree。此事实当时已足以把『全仓库脏文件都可能相关』缩成『cwd 脏项范围外、只需验证交付 worktree 的指纹与清洁度』。

## Short path
- rev-parse 对拍 cwd HEAD 与点名 tip：不等 ⇒ 第一未知量=交付 checkout 位置，立即停止对 cwd 脏因的任何深挖
- git worktree list（可按关键词过滤）一次读出 HEAD==tip 的交付 worktree，避免对全量列表二次重查
- git -C <交付worktree> rev-parse HEAD 'HEAD^{tree}' 且 status --porcelain 计数：tree 指纹符合父侧要求且清洁 ⇒ 审查锚点钉死
- 锚点之后再做对象寻址的内容读取（git show <c>:<path>、diff 基准..tip），每条范围结论都挂在已验证 tree 上
- 终局回执中把 cwd 镜像脏文件记为范围外澄清（计数+类别），并显式排除旁支 lane worktree 的脏项

## Stop conditions
- 交付 worktree 的 HEAD/tree 与任务给定指纹一致且 porcelain 清洁 ⇒ 锚点完成，转入内容级审查，不再回看 cwd 状态
- 任何 worktree/分支都不含目标 tip ⇒ 判交付缺失/引用错误并上报，不在 cwd 树上做替代审查

## Verification
- git -C <交付worktree> rev-parse 'HEAD^{tree}' 与父侧要求逐字符相等
- git -C <交付worktree> status --porcelain | wc -l 为 0，或每个脏项能归因到范围外 lane
- 最终裁决文本中所有工作树状态断言均可追溯到锚点验证回执，而非 cwd 的 status 输出

## Counterexamples
- 单 worktree 仓库且 cwd HEAD 已是目标 tip：指纹核验后直接进内容审查，worktree 定位步骤多余
- 纯对象寻址审查（仅 git show/diff by SHA）且结论不含任何工作树状态断言：checkout 位置不影响真值，可省锚定
- 被审对象恰是 cwd 的未提交改动（如 in-flight 工作收编审查）：必须全量枚举 cwd 状态，不能当范围外噪声跳过
