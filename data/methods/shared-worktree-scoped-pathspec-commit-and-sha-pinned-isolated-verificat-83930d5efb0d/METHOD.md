---
method_id: shared-worktree-scoped-pathspec-commit-and-sha-pinned-isolated-verificat-83930d5efb0d
name: shared-worktree-scoped-pathspec-commit-and-sha-pinned-isolated-verification
description: 在可能被并行会话/其他写入者共享的 git 工作区提交授权改动时，提交边界由授权文件集定义而非工作树状态：git status 与授权集做差集，多出的文件用有界 diff 分类 provenance（另一功能线即在途工作），保持原样不碰；提交一律显式 pathspec 分笔圈定授权文件，禁止 add -A/commit -a；提交后的验证必须在钉住该 commit SHA 的隔离（一次性）worktree 上跑，使门禁结论只反映提交本身、不受未提交并行改动污染；push 按准入流程走权威 remote。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1b498f1a-b510-4497-be53-2ae3460c91be:559:0caeea052e841eaabdda
evidence_refs: learning:learn:75565b573dc4
created_at: 2026-10-21T07:29:27.615132+08:00
updated_at: 2026-10-21T07:29:27.615132+08:00
---
## Trigger
准备在存在并行写入者（其他会话、格式化器、代码生成器）的共享工作区提交一批已授权/已交付的文件改动，且任务要求分笔 commit、另有 push 准入

## Discriminator
git status --short 的改动文件集与任务授权文件集的差集非空：对每个多出文件做有界 diff 即可分类归属（功能名/命名空间指向另一任务线）。这一当时即可得的事实同时决定两件事，提交必须用显式 pathspec 排除它们，且提交验证不能在脏共享树上跑

## Short path
- git status --short 取全量改动并与授权文件集做差集；未知量：工作区是否恰好等于授权范围
- 差集非空 → 对每个多出文件做有界 diff，只分类 provenance（属于哪条功能线），不修改不提交；未知量：这些改动是谁的
- 确认属并行在途工作 → 按任务分组用显式 pathspec 分笔提交授权文件；未知量：提交边界是否精确等于授权集
- 在钉住 commit SHA 的隔离/一次性 worktree 上跑验证与门禁；未知量：提交本身是否独立于未提交的并行改动而成立
- 门禁绿后按准入流程 push 至权威 remote（按 URL 身份钉死），用远程 SHA 回执核对
- 向用户显式报备并行在途文件的存在与未触碰状态

## Stop conditions
- 授权文件全部以显式 pathspec 提交完毕，每笔 commit 的文件清单等于预期 pathspec
- 隔离 worktree 中测试/门禁全绿且回执指向该 commit SHA
- 提交后 git status 确认并行改动文件仍以原样留在工作区（未被自己触碰）

## Verification
- 对每笔提交 git show --stat / diff-tree --name-only 核对文件集 == 授权 pathspec，无并行文件混入
- 提交后再次 git status：并行会话文件仍为 modified 且内容未变
- 门禁/测试回执来自 SHA 钉定的隔离 worktree，而非共享脏树；push 后 ls-remote 核对远程 tip

## Counterexamples
- 单人干净工作区且 status 恰好等于授权集：无需差集分类与隔离验证，直接提交即可，套用反而增加成本
- 多出的文件是自己早前命令的副作用（格式化重写、生成 reports 产物）：不能当并行工作静默排除，需先归属 provenance，再清理或入 .gitignore
- 并行改动与授权范围触碰同一文件：pathspec 无法切割语义冲突，应停下向用户/并行方协调而非强行分笔
