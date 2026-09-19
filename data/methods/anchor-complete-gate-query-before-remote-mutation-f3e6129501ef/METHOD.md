---
method_id: anchor-complete-gate-query-before-remote-mutation-f3e6129501ef
name: anchor-complete-gate-query-before-remote-mutation
description: 用户已授权某远程状态变更（合并/部署/重启）并给出前提条件与锚点（基线 SHA、PR 号、ID）时，先从这些推导出闸门所需的完整事实集（如 CI 终态、可合并性、head OID），用一次权威查询全部取回，并在变更前校验锚点一致；不要在闸门判定中穿插无关的状态查询（如旧 goal 状态）。远程变更落地后，先同步本地 ground truth，再读取随该变更到达的工件。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:72cadfe4-cbee-455c-ad5b-feaa06074185:679:7ec058ebcc0794d2abd5
evidence_refs: learning:learn:760742ed7e6a
created_at: 2026-09-19T02:36:50.527639+00:00
updated_at: 2026-09-19T02:36:50.527639+00:00
---
## Trigger
即将执行用户已授权、且以远程状态为闸门的变更动作（merge/deploy/重启），同时用户消息中已明确前提条件（如 CI 终态）和锚点（基线 SHA / PR 号 / 资源 ID）

## Discriminator
用户消息里的锚点+前提条件在发起任何查询之前，就已能枚举出闸门所需的完整事实集；若首次状态查询缺少锚点字段（如 head OID 未随 CI 状态一起返回），就必须补一次查询，且两次查询之间容易穿插与闸门无关的宽状态读取（返回的是上一个已完结 goal 的内容）

## Short path
- 从用户目标+动作前提推导闸门事实集：检查终态结论、mergeable/clean、head OID（用于与用户给出的基线锚点比对）
- 用一次权威查询（显式包含 head OID 字段）取回全部闸门事实；未知量：当前 head 是否就是用户锚点且全绿可合并
- 全绿且 OID 与锚点一致 → 立即执行变更；用变更回执验证 merge commit 的父提交恰为已验证的 head
- 远程 main 已被变更 → 在读取随变更到达的本地工件前先做 ff-only 同步，建立本地 ground truth
- 进入下一子任务（读模块现状 → RED 测试 → 实现），不再回头做发现类查询

## Stop conditions
- 闸门事实已在一次权威查询中全部取回且 head OID 与用户锚点一致 → 执行变更，不再追加状态查询（除非存在并发写者）
- 任一检查非终态/非绿，或 OID 与锚点不符 → 停止变更并报告差异
- 远程变更已落地且本地已同步、目标工件已可读 → 停止同步/发现类动作，进入下一子任务

## Verification
- 变更回执中 merge commit 的父提交包含已验证的 head OID，且用户锚点出现在合并后历史（log/merge-base 可证）
- 本地同步后 HEAD 与远程 main 一致，随合并到达的文件可直接读取且无需重试

## Counterexamples
- 分支可被他人并发推送：变更前的即时重查是必要的 freshness 守卫而非重复调用，过早的一次性查询反而会合入过期 head
- 检查仍在 PENDING：闸门不可判定，正确动作是轮询/延后，而非先取锚点字段
- 用户未给锚点且下游动作不需要 OID：按常规模板查询即可，刻意取全字段徒增噪声
- 纯本地工作流（远程与本地无分歧）：既无一次性闸门查询问题，也无同步步骤
