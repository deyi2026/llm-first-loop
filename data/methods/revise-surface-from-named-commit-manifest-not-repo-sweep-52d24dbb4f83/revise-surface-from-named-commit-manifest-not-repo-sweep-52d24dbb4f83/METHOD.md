---
method_id: revise-surface-from-named-commit-manifest-not-repo-sweep-52d24dbb4f83
name: revise-surface-from-named-commit-manifest-not-repo-sweep
description: 收到逐项 REVISE 裁决、且裁决消息本身具名候选标识（commit SHA）与产物构成（如'设计166行+BUG/OPT两队列'）并要求最小修订时，修订面文件清单直接由该具名 commit 的 manifest 对账得出：git show --stat 的文件数/行数与消息描述互相验证，worktree clean 时 commit 清单即磁盘现状。不要先做全库通配枚举（回执只会涌出同前缀历史文档噪音，还有误锚同日期同前缀其他 DESIGN 文档的风险）。随后按项锚定小步编辑，在产物内维护'审查项→落点→验证方式'映射，收尾跑机械核对（diff --check、安全扫描、被撤回表述的残留 grep、表格列数与分项数字闭合），回报时显式区分本轮已执行验证与仅属设计承诺的验证。
aliases: REVISE 裁决后怎么定位要改的文件, 按审查给的 SHA 锁定修订文件清单, git show --stat 对账修订面, 逐条审查意见落点映射表, 撤销旧说法后 grep 残留核对
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5a331d35-335d-4ca3-9a84-cf13f694d86c:112:fb237115d081fbc6e6a9
evidence_refs: learning:learn:daa3cb9ae5cc
created_at: 2026-11-16T01:35:05.622181+08:00
updated_at: 2026-11-16T01:35:05.622181+08:00
---
## Trigger
外部审查/裁决返回 REVISE，消息逐字给出候选产物标识（commit SHA/版本号）及其构成（文件数/行数），并限定最小修订范围与 lane/worktree，未要求扩大调查

## Discriminator
裁决消息已具名候选 SHA：该 commit 的 --stat 文件清单与行数可与消息中的构成描述直接对账（如166行设计+两队列），且 worktree clean 时 commit manifest 即磁盘现状——修订面在动手前已完全确定，任何仓库级发现都是多余分支

## Short path
- 恢复状态后先对具名 SHA 执行 git show --stat（或 git diff --name-only base..SHA），把文件数/行数与裁决消息的构成描述对账，锁定修订面
- read_file 全部目标文件取快照，作为后续锚定编辑的 expected_snapshot_ref 与行号基线
- 按裁决逐项做锚定小步编辑，同时在产物内维护'审查项→落点（节/行/队列ID）→验证方式'映射表，使每条意见可指认到具体修改位置
- 收尾机械核对：git diff --check、安全扫描、被撤回旧表述的残留 grep（残留只允许出现在勘误说明句）、表格每行列数与表头一致、分项数字之和闭合
- 隔离提交+checkpoint，逐项回报结论与新 SHA，显式声明哪些验证本轮已执行、哪些只是待实施轮的设计承诺

## Stop conditions
- 修订面与裁决描述对账一致（文件数/行数），且每条审查项都有落点与验证方式记录
- 机械核对全过、被撤回表述零残留（勘误说明除外），worktree 干净且新候选 SHA 已冻结

## Verification
- git show --stat <具名SHA> 输出的文件集/行数与裁决消息中的构成描述一致
- grep 被删除的旧论断字样，命中位置仅为勘误说明句
- 表格每行列数=表头列数；各分项计数之和等于总数（如登记前后两行账本加法闭合）

## Counterexamples
- 裁决只给主题不具名任何产物标识：无 manifest 锚点，文件名/内容检索才是合理首步
- 工作树含未提交改动：commit manifest ≠ 磁盘现状，须先以 git status/diff 取并集，不能只信 commit 清单
- 具名 commit 是触及大量文件的大合并而审查只针对子集：manifest 过宽，需结合消息点名的文件/章节再收窄
