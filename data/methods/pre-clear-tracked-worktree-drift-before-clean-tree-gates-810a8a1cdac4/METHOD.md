---
method_id: pre-clear-tracked-worktree-drift-before-clean-tree-gates-810a8a1cdac4
name: pre-clear-tracked-worktree-drift-before-clean-tree-gates
description: 受闸动作（publish/push/deploy 类）声明 clean tracked worktree 前置时，若早前工具回执已显示 tracked 文件处于 M 状态，不要等闸拒绝后才处理：先把会话自身产生的运行台账漂移（usage 流水、水印、方法卡回执等 append-only 文件）提交落账，再进入长耗时验证与闸动作。用回执中已可见的状态证据提前满足前置条件，避免『长测试→闸拒绝→补提交→重发』的空转循环；落账时机应紧邻闸动作，防中间步骤再生成漂移。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:de7f7e47-443e-42f9-9513-57ee99c8a21e:191:d14f5ae89282ee735a14
evidence_refs: learning:learn:721f4566bea4
created_at: 2026-10-13T04:08:37.973541+08:00
updated_at: 2026-10-13T04:08:37.973541+08:00
---
## Trigger
即将执行一个声明了前置条件（如 clean tracked worktree）的受闸动作，且此前任一回执中已可见 tracked 文件的 M 状态——尤其是本会话自身活动写出的运行台账/回执/水印类文件。

## Discriminator
knowledge-at-time：merge 回执的『合并后状态』段已逐行列出 3 个 ` M ` tracked 修改（experiences/usage.jsonl、experiences/.usage_watermark.json、data/methods/**/METHOD.md）——脏状态在闸动作之前就已可见；且这些文件是会话自身产生的台账，只能提交、不可还原。后续失败回执（tracked_worktree_dirty + next_step）证明该前置是硬闸。

## Short path
- 提交闸动作前，从最近回执或一次 git status 提取 tracked 修改清单；未知量：worktree 是否满足 clean 前置。
- 按来源分类：会话自身产生的运行台账/回执/水印 → 提交落账；来源不明的源码级改动 → 先查证归属与意图再处置，不为过闸盲目 commit。
- 若中间有长耗时步骤（如全量测试），把落账提交放在紧邻闸动作之前执行，而非仅提前一次。
- 重发闸动作；若再被拒，按拒绝码中的 next_step 单次修正，不盲目重试。

## Stop conditions
- worktree 已无 tracked 修改（或闸回执确认前置满足）→ 直接执行闸动作，不再重复检查
- 闸被拒且回执给出明确 next_step → 按 next_step 处置一次后重发；连续两次同类拒绝即升级诊断，不循环重试

## Verification
- 闸动作回执为 success 且不含 precondition/tracked_worktree_dirty 类拒绝码
- 落账提交的 diff 只含运行台账/回执/水印类文件，无源码或配置夹带

## Counterexamples
- tracked 修改来源不明或疑似误改时，不得为满足闸前置而盲目提交——须先核实内容归属（本集边界：程序不代 stash/commit/checkout，处置由模型执行并担责）
- 闸只拒绝 untracked/敏感文件、不要求 tracked clean 时，无需提前落账
- 中间长步骤本身会再生成台账漂移时，过早提交无效——落账必须紧邻闸动作，不能简化成『看到 M 就立刻 commit』
