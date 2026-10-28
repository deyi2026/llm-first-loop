---
method_id: empty-git-pathspec-widen-ref-scope-before-repo-hop-16dad9f1e81f
name: empty-git-pathspec-widen-ref-scope-before-repo-hop
description: 在仓库内用默认作用于当前 HEAD/checkout 的 git 查询（log/ls-files 路径匹配）找某文件或标识返回空时，不要立刻推断『变更在另一个仓库』并跳到文件系统级发现。默认查询范围只有当前 ref，而已在手的祖先/包含测试与分叉 diff 足以解释『我的 checkout 看不见≠仓库里没有』。先用 --all 或已知目标 ref 重发同一查询；命中即闭合，仍空且无任何祖先关联时才升级到换仓库或全局文件搜索。本集可省去：猜主仓库路径失败、截断的 ls+worktree 列表、两页水合翻页、跨目录 find。
aliases: 当前分支查不到文件是不是在别的分支, git log 空结果先查所有 ref, 找不到文件先扩分支范围再换仓库, checkout 里没有不等于仓库里没有, 查询为空先怀疑范围再怀疑位置
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f4fefaa7-cbbe-40e2-8ebf-3d7c794b1dd7:61:d850d8d37eb5fabb9eb5
evidence_refs: learning:learn:5afed2662c6a
created_at: 2026-10-24T22:53:29.496639+08:00
updated_at: 2026-10-24T22:53:29.496639+08:00
---
## Trigger
在单一仓库内定位某文件/路径/标识，默认 scope=当前分支或 index 的 git 查询返回空，且手头已有祖先测试/包含测试/与 main 的分叉 diff 等证据表明相关提交在其他 ref 上

## Discriminator
空结果出自一条 scope 已知为当前 ref 的查询（git log 默认 HEAD、ls-files 默认 index），而已有独立证据（祖先测试显示实现提交 IN main、当前分支与 main 分叉数十文件）表明目标内容在别的 ref——『我的分支树里没有』与『本仓库没有』是两个命题

## Short path
- 收到空结果后先问：这条查询的 scope 是什么（HEAD/index/单 ref）
- 若 scope=当前分支且已有证据显示相关提交在其他 ref：用 --all 或该 ref 重发同一查询（git log --all -- '*目标*'，或直接 git show --stat <已知在 main 的提交>）
- 命中即取得文件↔提交映射，结合已有祖先测试直接回答原问题，不再做文件系统级发现
- --all 仍空且无任何祖先/包含关联把变更绑到本仓库时，才升级为换仓库或全局搜索，并注明『已排除本仓库全部 ref』

## Stop conditions
- --all/目标 ref 查询命中目标文件或其提交映射，定位问题闭合
- 查询已是全 ref scope 仍为空且无关联证据：空结果即本仓库层面的阴性结论，此时才允许离开 git 层

## Verification
- 确认命中提交所在的 ref 与早前祖先测试结果一致（如实现提交 IN main）
- 用 git ls-tree <ref> -- '*目标*' 复核该 ref 的树中确有该文件

## Counterexamples
- 目标是未纳入版本控制的工作树/运行时产物（日志、临时导出）：任何 ref 都查不到，文件系统枚举才是正确第一通道
- 已有独立证据（remote 列表、文档明示另一仓库 URL）且本仓库 ancestry 与变更无关联：可直接去另一仓库，不必先 --all
- 查询本身已是全 ref scope 仍为空：扩大范围无处可扩，空结果即为结论
