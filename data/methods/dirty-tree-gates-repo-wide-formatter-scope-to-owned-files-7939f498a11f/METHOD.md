---
method_id: dirty-tree-gates-repo-wide-formatter-scope-to-owned-files-7939f498a11f
name: dirty-tree-gates-repo-wide-formatter-scope-to-owned-files
description: 准备对仓库根跑 auto-formatter（ruff format / black / prettier / lint --fix）时，先用本 run 已有的 git status 回执做门禁：若 dirty tracked 文件超出本任务 change-set、且仓库不强制格式化，就把 formatter 收窄为显式文件路径，只碰本任务新建/拥有的文件。判定事实在动手前全部可见；误跑全仓会把语义 diff 与格式噪声混叠成大量 hunk，届时不要手工逐处改，按 hunk 级 token 流结构等价过滤后 git apply -R 回滚纯重排 hunk，误删字节用 blob sha 逐字节还原。
aliases: 全仓格式化把没提交的改动搅浑了, 只格式化自己这次动过的文件, 误跑格式化后撤掉纯重排 hunk, 跑格式化前先看脏文件清单, black 或 prettier 重排了在途代码怎么恢复
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:73172f2a-c1f6-4868-9611-d4af1d463c48:1658:cbf77fa671561de83483
evidence_refs: learning:learn:8df221f84e64
created_at: 2026-11-03T20:47:24.457918+08:00
updated_at: 2026-11-03T20:47:24.457918+08:00
---
## Trigger
任务收尾或清理阶段，准备运行 auto-formatter / lint --fix / 一次性重排类工具于仓库根；本 run 早前的 git status 回执已显示 dirty tracked 文件，且其中部分改动不属于本任务 change-set

## Discriminator
动手前已可观察的两件事实组合：(1) 本 run 内早前的 git status 显示多个 M 类 tracked 文件携带未提交语义改动、超出本任务范围；(2) 仓库无格式化强制（无 format CI gate / pre-commit / format-only 提交惯例）。两者同时成立时，repo-wide format 的期望收益为零，唯一可预期产物是把语义 diff 与格式噪声混叠。

## Short path
- 运行任何仓库级 transformer 前，先取本 run 已有 git status 回执（或重跑一次），列出 dirty tracked 文件清单
- 把清单切成两桶：本任务已拥有（本任务新建/修改）vs 在途他人改动；第二桶非空且仓库不强制格式化时，禁止在仓库根跑 formatter
- 格式化需求收窄为显式路径参数：只格式化本任务新建/拥有的文件
- 若已误跑：不手工逐处改——按 hunk 粒度做 token 流结构等价判定，git apply -R 只回滚纯重排 hunk；折行类 hunk 用放宽判据二次回滚；误删内容用 blob/artifacts 按 sha 逐字节还原

## Stop conditions
- 本任务文件已按显式路径格式化（或确认整体跳过），git diff 中不再混入非本任务文件的格式噪声
- 确认仓库强制格式化（CI gate / pre-commit 存在）时停止套用本门禁，转为顺序问题：先提交语义改动，再独立做 format 提交

## Verification
- 回滚后逐文件复核 git diff：本任务语义改动仍在（新增行数与预期一致），其余 hunk 与格式化前 token 流等价
- 被误删/误改字节用 blob sha 与当前文件逐字节比对一致后再继续
- 跑一次相关测试面确认零行为变化（纯格式回滚不应改变任何断言结果）

## Counterexamples
- 仓库 CI 或 pre-commit 强制格式化：格式化是必需交付物，门禁失效，只能改为先语义 commit 再 format commit 的顺序安排
- working tree 干净，或全部 dirty 文件都属于本任务 change-set：全量格式化不产生跨任务噪声，可直接跑
- 工具为只读检查模式（ruff check / prettier --check / --diff）：不改文件，无需此门禁
