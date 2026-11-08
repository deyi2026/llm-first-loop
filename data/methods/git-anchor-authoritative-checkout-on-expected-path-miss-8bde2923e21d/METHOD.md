---
method_id: git-anchor-authoritative-checkout-on-expected-path-miss-8bde2923e21d
name: git-anchor-authoritative-checkout-on-expected-path-miss
description: 任务/claim 回执给出的 expected_paths 在当前 cwd 全部 miss、而更早的权威回执（goal checkpoint）已点名工作所在 feature 分支时，第一未知量不是「文件在哪」而是「哪个检出/worktree 是权威工作区」。用一次 git 锚定（pwd + branch --show-current + git worktree list）回答，再在该 worktree 内做限定范围检索；不要转全仓库内容/文件名搜索——镜像仓（.releases/*、.bak-）会返回大量过期拷贝噪声。本集先经历两次路径 miss + 三轮宽搜索（命中设计文档与 14 条 .releases 镜像）才跑 pwd/git branch 发现 main 检出与 feat 分支 worktree 的错位。
aliases: 路径不存在先看自己在哪个分支, expected_paths全miss就查git worktree list, 搜到一堆.releases镜像说明找错检出了, 多worktree仓库动手前先锚定检出, checkpoint点名了分支就先去那个工作树
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:453:2987b01707517cae0890
evidence_refs: learning:learn:9f5dd59f9618
created_at: 2026-11-08T00:07:26.050225+08:00
updated_at: 2026-11-08T00:07:26.050225+08:00
---
## Trigger
任务/claim 回执提供 expected_paths 或 goal checkpoint 点名 feature 分支；直接读路径返回「路径/目录不存在」；仓库存在多检出形态（.worktrees/、.releases/ 镜像、detached HEAD 拷贝）

## Discriminator
进入宽搜索前已可见两条事实：①首个权威回执（goal checkpoint）明确写着「N 提交在 feat/<分支>」——工作在命名分支上而非当前检出；②claim 的 expected_paths 与 cwd 实际包布局不符的首个 miss 回执本身即证明 cwd 不是权威检出。二者合并把「全仓库找文件」缩成「定位持有该分支的检出」

## Short path
- 读 goal/task 回执，记下其点名的分支/提交位置（未知量：工作权威位置在哪）
- 收到 expected_paths 后做一次路径试探（合法首探）
- 首个「路径不存在」回执 + 回执已点名分支 ⇒ 立即一次 git 锚定命令：pwd && git branch --show-current && git worktree list（未知量：cwd 是否权威检出、目标分支挂在哪个工作树）
- 在命中的 worktree 内做限定范围的文件名/结构检索，确认真实包布局（expected_paths 的包名可能与实际不同，如 lfl_agent/ vs src/llm_loop/）
- 锚定后再进入实现/挂载/提交，全部路径操作以该 worktree 为根

## Stop conditions
- git 锚定已唯一确定权威检出，且目标文件或包布局在该检出内定位成功
- expected_paths 直接命中当前 cwd（锚定动作可跳过）

## Verification
- 锚定后所有路径读写都发生在该 worktree 的 git status/branch 上可见
- 不再出现路径 miss 后转全库搜索的回执；检索结果不含 .releases/、.bak- 镜像拷贝

## Counterexamples
- 单检出仓库且 expected_paths 直接命中——无需锚定，直接干活
- 路径 miss 是因为文件本该由本任务新建（greenfield 文件，如新工具模块）——miss 是预期而非走错检出的信号，判据看父目录/包是否存在：包目录整体 miss 才指向错检出
- 分支尚未 fetch/建 worktree——worktree list 不命中时转入 checkout/fetch 决策，而不是退回宽搜索
- .releases/* 中的同名命中是历史发行镜像，永不当工作真值
