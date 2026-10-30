---
method_id: reanchor-plan-referents-probe-ephemeral-then-scan-pending-commit-filelis-f644fd0269d3
name: reanchor-plan-referents-probe-ephemeral-then-scan-pending-commit-filelist
description: 跨轮执行旧建议时，计划参数引用的易失物（/tmp 数据源、由未推区间派生的范围数）只是上轮快照：/tmp 文件会消失、并发会话会把区间推空。先做两类廉价探针——引用物存在性（ls/stat）与区间实测（git log --name-only origin..HEAD）——并注意：上轮'没找到'只覆盖工作树与常规搜索面，不覆盖未推提交内容；引用工件可能只存在于 pending 提交里，枚举其文件清单即可找到持久后继（如已提交的队列清单），避免全库广搜或从零重建。与 remeasure-tree-scope 卡互补：那张管暂存范围，这张管引用物存续与后继定位。
aliases: 上轮找不到的文件去未推送提交里找, tmp 数据源没了别全库搜, 继续执行旧计划先核对引用物还在不在, 待推区间变了重新实测冻结范围, 队列名单来源消失从提交里复现
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cab051cc-c0ca-4a09-b848-6d4a00ec0ffe:1383:31840c0cf0cdf6a2e347
evidence_refs: learning:learn:5e1282c6b6cf
created_at: 2026-10-30T11:06:44.753963+08:00
updated_at: 2026-10-30T11:06:44.753963+08:00
---
## Trigger
跨轮/跨会话执行先前给出的计划或建议，且参数引用了：易失路径下的数据源（/tmp 等）、由 repo 状态派生的范围（待推提交区间、untracked 集），或上轮已断言某引用工件『没找到』。

## Discriminator
引用物是否位于按契约易失的位置，以及 origin..HEAD 各提交的文件清单里是否已有持久后继。上轮的 not-found 结论只证明工作树/常规搜索面没有，不证明它不存在——并发会话新增的未推提交是常规搜索覆盖不到的存放面。

## Short path
- 把计划参数按引用物耐久性分类：易失路径 / repo 状态派生范围 / 工作树稳定文件。
- 易失路径做一次存在性探针（ls/stat）；缺失即判死，不在库内广搜它的替代副本。
- 派生范围做一次区间实测（如 git log --name-only origin..HEAD），顺带取得 pending 提交的文件清单。
- 对『没找到』的引用工件，先在 pending 提交文件清单与 untracked 面里找持久后继；命中即以它复现现行口径。
- 用实测参数执行，并把记忆数字与实测值的差值向用户显式报告。

## Stop conditions
- 计划全部参数已锚定到当前可验证的引用物（存在且与现行口径一致）。
- 易失源缺失且提交内无后继：停止挖掘，转向现行权威口径重建或向用户求证。

## Verification
- 后继工件能用 git log --name-only / git show --stat 从已核提交复现。
- 实测区间与准入/推送闸实际冻结的范围一致。

## Counterexamples
- 引用物是仓库内稳定文件且无并发写入者：直接读即可，无需枚举提交内容。
- 易失源仍存在且形态符合预期：直接使用，不必重建或换源。
- 无 pending 提交、untracked 与工作树均无该工件：此时广域搜索或询问用户才是正确动作。
