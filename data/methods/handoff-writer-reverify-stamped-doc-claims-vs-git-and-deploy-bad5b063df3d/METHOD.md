---
method_id: handoff-writer-reverify-stamped-doc-claims-vs-git-and-deploy-bad5b063df3d
name: handoff-writer-reverify-stamped-doc-claims-vs-git-and-deploy
description: 写跨会话交接文档时，仓内设计书/状态文档的 as-built 或实现状态表自带『截至某 commit/日期』戳；当该戳早于已知最新事件（goal checkpoint、任务回执里的新修复提交或新部署 generation）时，表里的实现/部署断言不可直接转写进交接。逐条用活源重验：修复是否已上线用 git merge-base --is-ancestor <fix> <deployed>；部署态用服务 status 的 matches_desired_generation；并发写者用 git status --porcelain + 文件 mtime。交接中把被推翻的旧口径显式标『过期，以何为准』、已闭环项标『不要重做』，并写明新会话第一步。不要先做全库/归档关键词扫描——权威文档路径与必载断言 goal 状态已给出。
aliases: 写交接前先核修复是否真上线, 交接文档别照抄设计书旧口径, as-built 表过期怎么判断, 部署版本和文档对不上时交接怎么写, merge-base 验证已部署, 交接文档标注过期状态
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:36553398-1c59-4c05-927f-23e13f8396e6:3958:d1962b16f31ed914e985
evidence_refs: learning:learn:309b9fd7b986
created_at: 2026-10-31T14:58:43.312711+08:00
updated_at: 2026-10-31T14:58:43.312711+08:00
---
## Trigger
用户要求写跨会话/换环境交接文档（如会话过长、沙盒受限需新开会话）；仓内权威设计书或状态文档含自标注『截至 <commit>，<日期>』的 as-built/实现状态表；且 goal 状态、checkpoint 或任务回执中已出现晚于该戳的事件（新修复提交、新部署 generation、新用户裁决）

## Discriminator
文档表头的 as-of 戳与已知最新事件的 commit/时间差距——两者均已到手（文档已读、goal/任务回执已返回），无需新工具调用即可判出该表可能过期；一旦判过期，『已实现/未实现/已部署/未闭环』类断言降级为待验线索，而不是交接事实

## Short path
- 从 goal 状态与任务回执枚举交接必载断言：未决任务、用户裁决红线、『下一会话第一步』（如部署后 live 复验）
- 读同目录最新兄弟交接文档与目标设计书的裁决/as-built 段，抄下每张表的『截至 <commit>，<日期>』戳；跳过对 archive/worktree 副本的全库关键词扫描（goal 已给出权威路径）
- 对戳早于最新事件的可变断言逐条活源重验：merge-base --is-ancestor <fix> <deployed_sha> 验已上线；服务 status 验 generation 与 matches_desired_generation；git status --porcelain + stat mtime 验是否存在分钟级活跃写者
- 成文：已验事实带来源与时间戳；被推翻旧口径显式标『过期，以 <commit/实测> 为准』；已闭环项标『不要重做』；活跃写者文件给出『禁止 stash/reset/提交他人改动』禁令；新会话第一步写成命令级动作
- 每条断言要么有活源回执支撑、要么显式标注『未验+依据』，即停，不再追加枚举

## Stop conditions
- 交接内每条可变状态断言均有活源回执支撑，或显式标注『未验，依据=文档戳/沙盒限制』
- 用户裁决与红线逐条在场，且未被任何旧文档口径覆盖
- 新会话第一步已是命令级可执行动作，接手者无需推翻交接内任何事实即可开工

## Verification
- 对每笔『已修复且已部署』断言：git merge-base --is-ancestor <fix> <部署 commit> 退出码 0，且服务回执 matches_desired_generation=true、barrier 为空
- 被标『过期』的文档段落确实在其戳之后有落地 commit（git log -1 --format=%ci <fix> 复核时间晚于文档戳）
- git status 脏文件的 mtime 相对交接落盘时刻的『活跃写者』结论仍成立（动手前重 stat 一次）

## Counterexamples
- 文档 as-of 戳等于已知最新部署/提交（无更新事件）→ 直接转写即可，全量重验是浪费调用
- 交接只载稳定内容（用户裁决、任务定义、红线），不含 git/部署可变状态 → 不需要活源重验
- 目标是 append-only 阶段台账（每条自带时间戳且不可变）→ 读尾部即得最新态，不存在整表过期问题
- 活源（git/服务 status）在当前沙盒不可达 → 交接必须显式降级为『未验』标注并给出继任者重验命令，不得按文档猜测当前态
