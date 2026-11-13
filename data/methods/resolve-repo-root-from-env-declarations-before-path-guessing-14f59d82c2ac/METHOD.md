---
method_id: resolve-repo-root-from-env-declarations-before-path-guessing-14f59d82c2ac
name: resolve-repo-root-from-env-declarations-before-path-guessing
description: 任务以相对路径/仓库名锚定工作区而当前 cwd 不是仓库时，把『绝对根在哪』当作第一未知量，从会话已声明处解析：项目前缀环境变量、沙箱回执注明的工作区、开局记忆检索已引用过的 env 变量。多个根并存时分类为活 git 工作树 vs 固定 release 快照，git 操作选前者；仅当环境零声明才做有界路径枚举，不要逐个试探 ~/repo、~/dev/repo 等猜测目录。
aliases: 仓库路径猜不到先查环境变量, worktree 相对路径怎么定位仓库, LFL 多个根变量选 git 工作树, release 快照目录跑不了 git, 沙箱工作区根从哪读
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:767d2e4a-13b1-4ede-b805-3424d3e72a84:0:706c82c366a23afe6cbb
evidence_refs: learning:learn:da0e949cb0de
created_at: 2026-11-13T07:49:47.026342+08:00
updated_at: 2026-11-13T07:49:47.026342+08:00
---
## Trigger
任务文本用相对路径（如 .worktrees/<name>）或仓库名引用目标工作区，shell/沙箱默认 cwd 不是该仓库，且下一步倾向于枚举常见猜测路径定位仓库

## Discriminator
开局检索/工具回执中已出现项目根的声明证据：experience 卡点名过会话 env 变量（如 LFL_WORKSPACE_ROOT 指向 .releases 快照）、工具回执注明『沙箱仅允许写工作区』——根是已声明量而非待猜量；首个 pwd 回执显示 cwd 在非仓库目录，同时证明 cwd 推导不可用

## Short path
- 未知量=绝对仓库根：env 过滤项目前缀/workspace/root 类变量，得到少量候选根
- 分类候选根：对每个根跑 git rev-parse --show-toplevel；活工作树成功，固定 release 快照根不可用于 git 流程，排除
- 在活 git 根上 git worktree list，按任务点名的 worktree 名/分支/commit 匹配并 cd 进入
- 以任务文本给定的 commit/tree 校验 HEAD，一致即停止定位，进入实际任务盘点

## Stop conditions
- 已进入点名 worktree 且 HEAD/tree 与任务给定的权威身份一致
- 环境扫描无任何项目根声明（干净容器/全新 shell）→ 转有界路径发现，本方法不适用

## Verification
- git worktree list 显示点名 worktree，分支与 commit 匹配任务文本
- 被排除的快照根上 git rev-parse 失败或指向只读 .releases 快照，证实分类正确

## Counterexamples
- 任务已给出绝对路径：直接 cd，跳过根解析
- 目标本身是冻结 release 快照（部署核验）：快照根才是正确工作区，不要换成 git 树
- 会话继承的 env 根指向过期 checkout：env 值只是线索，必须以 git 校验为准
- 无任何项目 env 变量与历史回执的干净环境：有界猜测发现是唯一途径
