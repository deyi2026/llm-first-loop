---
method_id: named-artifact-git-metadata-before-repo-enumeration-5f43d6c96a8d
name: named-artifact-git-metadata-before-repo-enumeration
description: 当任务要操作一个远端实体（如 PR #N）但未直接给出仓库 slug，而任务文本/计划已引用一个与该实体绑定的本地 git 工件（如名字含实体编号的临时 worktree）时，先用该工件的 git 元数据（.git 指向的主仓库、remotes、HEAD）一次性解析目标仓库与 head SHA，再到权威远端核验实体后执行操作；不要先枚举本地全部仓库、跨平台逐个猜测远程。网络慢时，基线核验优先服务端 compare API 而非本地 fetch，且若后台 fetch 已被 API 取代应及时终止。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:1089:e0e13aaa06073fe56037
evidence_refs: learning:learn:c0b8dfb3f3fc
created_at: 2026-09-18T05:23:57.714241+00:00
updated_at: 2026-09-18T05:23:57.714241+00:00
---
## Trigger
任务需操作远端实体（PR/issue/分支）但仓库 slug 未直接给出；同时计划或上下文引用了绑定该实体的本地 git 工件（例如以 PR 编号命名的临时 worktree 需要清理），或在会话证据检索未命中时仍存在此类工件线索。

## Discriminator
工件名字/角色明确绑定目标实体（worktree 名含 PR 编号，且 worktree 按定义就是其所属仓库的检出）：读一个 .git 文件 + git remote -v 即可得到 repo slug、本地镜像路径和 head SHA，把『N 个候选仓库』缩为 1 个可验证下一跳。此事实在任务起点（计划文本提到该 worktree）即已存在，无需任何后续发现。

## Short path
- 从任务文本/计划提取绑定目标实体的本地工件：优先直接取其已知路径；若路径不可用，按名字模式做窄查找（如主仓库 git worktree list 或临时目录按 *<实体编号>* 过滤），不做全盘/全仓库枚举。
- 读工件 git 元数据：.git 文件的 gitdir 得主仓库与镜像路径；git remote -v 得远端 slug；HEAD 得当前提交 SHA。
- 用所得 slug 在权威远端核验实体（如 gh pr view N -R <slug>），确认 state/mergeable/CI，并用标题、分支名、headRefOid 与工件 HEAD 交叉验证编号命中不是同号无关实体。
- 合并/操作前的基线核验优先服务端 compare API（base...head，behind_by=0），避免慢网络下本地 fetch；若已启动的后台 fetch 被服务端结果取代，及时终止释放资源。
- 执行操作后仍用同一 slug 验证结果（mergedAt、main 上 CI、merge commit），清理工件前先确认其 status 干净。

## Stop conditions
- 工件元数据给出唯一 repo slug，且远端实体的编号/标题/分支/head SHA 与工件一致：停止仓库定位，直接进入操作与验证。
- 工件不存在、元数据与实体不匹配（如 remotes 指向 fork 而实体在上游）、或工件名不含实体标识：停止沿该边走，回退到会话证据检索、受控枚举或向用户询问。

## Verification
- 远端实体的 headRefOid 与本地工件 HEAD SHA 一致。
- 工件的 remote 指向的仓库中该编号实体存在，且标题/分支内容符合任务语义（防止命中其他仓库的同号无关实体）。
- 关键基线判断（如 head 是否包含 main tip）以远端权威 API 结果为准，不依赖本地可能过期的缓存。

## Counterexamples
- 任务已直接给出 repo slug：无需工件解析，直接操作，多读工件反而是浪费。
- 工件名是通用名（tmp-checkout、baseline 等）不含实体标识，或多个仓库存在同编号实体且工件线索含糊：命名/绑定不再构成判别器，应回退受控枚举。
- 工件已被删除或失效、remotes 已变更（指向 fork 而非 PR 所在上游）：元数据会误导定位。
- 本地不存在任何与实体绑定的工件：此方法无起点，只能走会话证据检索或询问用户。
