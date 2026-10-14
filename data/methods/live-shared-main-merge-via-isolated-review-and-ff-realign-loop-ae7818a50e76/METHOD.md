---
method_id: live-shared-main-merge-via-isolated-review-and-ff-realign-loop-ae7818a50e76
name: live-shared-main-merge-via-isolated-review-and-ff-realign-loop
description: 共享仓库中另一会话活跃推进 main 时（入口 status/reflog 已可见他人未提交文件与新鲜提交时间戳），复审期间固定的 rebase 基在落地前就可能过期，ff 会被拒。方法：昂贵复审与长测试全部放隔离 worktree，共享树零扰动；落地压成单命令原子序列『重读 main tip → 算新增提交与分支路径交集 → rebase → 立即 ff』，零交集则 rebase 纯机械无需扩大复审；ff 被拒视为并发写信号、循环下一迭代而非错误。合并后在真实 main 树复跑验证，快照比对他人未提交文件。本集因先固定基再长测，ff 一次被拒，多花一轮重对齐。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:33d3039e-2906-4f07-9dc7-517532290686:479:a73380ac93bebbcbe3c7
evidence_refs: learning:learn:7eb485642fdc
created_at: 2026-10-14T19:08:48.207271+08:00
updated_at: 2026-10-14T19:08:48.207271+08:00
---
## Trigger
需把已复审分支合入存在活跃并发写者的共享 main：共享树带另一会话未提交文件、main reflog 提交时间戳新鲜、复审+测试耗时可能跨越并发提交窗口

## Discriminator
入口一次状态检查即可判定合并目标是移动靶：他人脏文件在共享树 + reflog 近期时间戳 + main 与远端已同步 ⇒ 任何早前验证过的 rebase 基在 ff 前都可能过期，不能当作持久事实

## Short path
- 入口读 branch 状态、main reflog 时间戳、脏树文件归属，判定 main 是否活跃移动靶
- 全部复审、类型检查、测试在隔离 worktree 进行，共享树不承担任何中间扰动
- 复审期间 main 出现新增提交时，先机械计算其与分支的路径交集：零交集 ⇒ rebase 纯机械，复审结论继续有效
- 落地为单条原子命令：重读当前 main tip → rebase 到该 tip → 立即 ff，最小化竞态窗口；ff 被拒不回滚计划，直接进入下一轮同构迭代
- 合并后在共享 main 工作树复跑类型检查与全量测试（worktree 结果不可迁移），并 diff 前后快照确认另一会话未提交文件未受影响
- 清理隔离 worktree；main 领先远端的提交清单报告用户，push 决策交还用户

## Stop conditions
- ff 成功且合并后 main 顶同时包含并发会话提交与本分支提交，领先 origin 数符合预期
- 合并后真实 main 树上类型检查与全量测试全绿
- 另一会话未提交文件前后快照完全一致
- 已向用户报告领先提交并等待 push 指示

## Verification
- git log 确认分支提交位于 main 顶端且并发会话提交未被绕过或覆盖
- 在合并后的共享树上（而非复审 worktree）复跑类型检查与测试套件
- 合并前后对他人脏文件的快照 diff 为空
- 路径交集结论来自机械 diff/comm 输出而非目测

## Counterexamples
- 单写者或 main 已冻结的仓库：基线一次验证即可，重对齐循环徒增开销
- 并发新增提交与分支路径交集非空：零交集捷径失效，必须真冲突解决并复审重叠文件后才能 ff
- 仓库策略要求 no-ff 合并提交：ff 拒绝不再是无害重试信号，需改用受控 merge 流程
- 另一会话未提交文件恰与分支改动同路径：任何 ff/checkout 都会触碰他人工作区，应等待或协调而非绕行合并
