---
method_id: preclear-untracked-residue-by-origin-before-snapshot-gates-1950512151b0
name: preclear-untracked-residue-by-origin-before-snapshot-gates
description: 在调用会冻结/快照整个 worktree 的准入或审查闸（full_test/git_push/publish 类 admission）之前，若早前回执（持久化 state 快照、子代理审查报告、git status 输出）已枚举出未跟踪或修改类残留，不要等闸拒绝后再诊断：先按来源分类预清——会话自身的 append-only 台账漂移→提交落账；过期工具临时产物（如合并程序遗留的临时 git 目录）→移出 worktree 并保留备份；小型预期治理工件→不动。持久 state 里『勿动』的整批标注不免除预检：闸拒绝（如 untracked_file_too_large）后仍按来源分类，只处置会阻塞闸的那一类。与『先提交 tracked 漂移』卡互补：untracked 维度的正确动作是隔离而非提交。
aliases: untracked 太大被准入拒绝, 遗留临时目录挡住审查闸, 快照准入前 worktree 预检, 干净树前置包含 untracked 残留, untracked_file_too_large 拒绝怎么处理, 合并遗留 .mergegit 临时 git 目录
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:80f5e2cd-19c2-42bb-8bca-1c0a01cc2a48:3632:c3ed32bcd7c1eef02fc5
evidence_refs: learning:learn:5d46d8b133da
created_at: 2026-10-25T22:14:06.245652+08:00
updated_at: 2026-10-25T22:14:06.245652+08:00
---
## Trigger
即将调用以冻结/快照 worktree 状态为前置的准入、审查或发布类闸动作，且早前回执（state 快照、子代理报告、git status）已明确枚举工作区存在 untracked 和/或 modified 残留

## Discriminator
残留清单与来源线索已出现在手头回执中（如合并程序遗留的 .git 式临时目录、append-only 治理回执、本会话台账文件），且该准入已知会整体审查 worktree 状态——因此在发起闸之前即可用一次 du/status 廉价预检判定哪类残留会超限，无需等闸回报拒绝理由

## Short path
- 发起准入前，从早前回执提取已枚举的 untracked/modified 残留清单，不发起宽发现
- 廉价预检：对每项残留 du -sh / git status --porcelain，识别可能超出闸容量（大小/条数）的类别
- 按来源分类处置：会话台账漂移→提交落账；过期工具临时产物→移出 worktree 到备份位置（不删除、不提交）；预期小工件→原样保留
- 只处置会阻塞闸的类别后一次性发起闸动作，避免『拒绝→诊断→整改→重发』空转循环
- 闸受理后核对被隔离项在备份位置存在、tracked 树与处置前一致

## Stop conditions
- worktree 仅剩闸预期/容忍的小型工件（如治理回执）→直接发起闸
- 残留疑似并行会话的在途工作→停止自行处置，转所有权确认/上报路径
- 残留来源与后续作用不确定→只备份隔离，不删除不改内容

## Verification
- 准入首次提交即受理，无 untracked_file_too_large / dirty worktree 类拒绝
- 被隔离产物在备份位置可寻址可恢复；git status 的 tracked 部分与处置前一致
- 保留类工件未被触碰，后续闸（push/publish）同样一次通过

## Counterexamples
- 闸明确声明 untracked 文件不在检查范围（只查 tracked clean）→预清 untracked 属多余动作
- untracked 大文件正是闸要审阅的输入或预期产物（如闸将检查的回执/快照）→绝不可移走
- 共享脏检出区中残留是他人未提交的在途工作→移动或提交都会破坏对方（转所有权路径）
- 残留可能仍被未完结流程使用（合并程序未收口）→只隔离备份，绝不删除，也绝不把工具临时目录提交进分支历史
