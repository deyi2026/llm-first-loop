---
method_id: fetch-refresh-before-shared-remote-push-d4c26f4e9abb
name: fetch-refresh-before-shared-remote-push
description: 当要向可能被并发更新的共享远端既有 ref（尤其活跃仓 main）写入或选择发布形式时，必须先在本会话 fetch 刷新权威状态，再依据真实拓扑（仅领先→快进推；分叉→推分支+按惯例建 PR；落后→先整合）行动；绝不基于本地 tracking ref 的陈旧视图直接规划 main 推送。全新分支推送不受此约束。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e6118296-8fb6-4727-8287-155a579a029b:633:ea3e8df5a2dd824e7c58
evidence_refs: learning:learn:42c62876c5c3
created_at: 2026-09-17T15:29:50.857933+00:00
updated_at: 2026-09-17T15:29:50.857933+00:00
---
## Trigger
准备向共享远端的既有 ref 推送，或要根据『本地 vs 远端』关系决定发布形式（直推/PR/先拉取），且本会话尚未执行 fetch；环境中存在并发写入信号（并行会话、PR 线、数分钟内新增的合并提交、旧 PR 引用无法解析）。

## Discriminator
本会话 trace 中没有任何 git fetch，却已从本地 tracking ref（lfl/main=3eaae8f6）得出『本地领先、快进可推』并据此推 main；同时刻已可见的并发信号：GraphQL 报 PR #26 无法解析（上轮引用已失效）、22:27 刚产生 gen10 合并提交 d3f6b150——三条事实共同表明远端状态新鲜度未验证、仓库正被并行更新，此时『可快进』是不可信结论。

## Short path
- 1. 核对运行态/部署记录，确认要保住的提交链（gen10=d3f6b150 全链）本地就绪——未知量：要发布的工作是什么、是否完整。
- 2. 同一轮执行 git remote -v 识别活跃远端（区分 lfl 与 legacy origin）并 git fetch <active-remote>——未知量：远端真实 tip 与本地拓扑关系。
- 3. 依据新鲜拓扑定发布形式：仅领先→快进推 main；分叉（远端有并行 t0-batch 线）→推分支+按仓库 PR 惯例建 PR，绝不硬推分叉 main。
- 4. 网络推送一律注入非交互 credential helper（gh auth git-credential）并后台执行——避免 60s 前台超时（本例超时即凭据等待所致）。
- 5. 推送回执/PR URL（如 pull/27）确认集成路线；注册后续观察提醒后停止。

## Stop conditions
- 远端 tip 已本会话 fetch 刷新，拓扑已知，发布形式已据此一次性选定。
- 新工作分支已在远端且集成路线（PR URL 或推送回执）已确认可解析。

## Verification
- 推送输出中不得出现 '! [rejected] non-fast-forward'；若出现，必须先 fetch 分析分叉内容再决策，而非换参数或 force 重推。
- gh pr view / PR URL 可解析（对照本例 PR #26 不可解析的教训：引用过的远端对象要验证归属与编号空间）。
- fetch 后 main..remote 与 remote..main 双向差集与所选发布形式一致。

## Counterexamples
- 单写者仓库且本会话刚 fetch 过——再 fetch 是纯开销，直接按已知拓扑行动。
- 推送全新命名分支——不存在共享 tip，无需先 fetch 即可安全推送（本例分支推送在陈旧 ref 下同样成功）。
- 只读检查/分析任务，不写共享远端——不适用。
- 仓库惯例就是单写者直推 main（无 PR 流）——强制建 PR 反而违反协作约定。
