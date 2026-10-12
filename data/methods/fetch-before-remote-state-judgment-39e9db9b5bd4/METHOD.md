---
method_id: fetch-before-remote-state-judgment-39e9db9b5bd4
name: fetch-before-remote-state-judgment
description: 在多远端或有并行推进迹象的工作区，任何基于 remote-tracking refs 的 ahead/behind/fast-forward 判断、以及对共享远端的 push/PR 写操作之前，必须先在本会话内 fetch 目标远端刷新 tracking refs。stale tracking refs 只是上次 fetch 的快照，不是远端当前真值；先 fetch 看清真实关系（领先/落后/分叉），再决定直推快进还是分支+PR，避免被 non-fast-forward 拒绝后返工。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e6118296-8fb6-4727-8287-155a579a029b:633:ea3e8df5a2dd824e7c58
evidence_refs: learning:learn:42c62876c5c3
created_at: 2026-09-17T15:29:14.291916+00:00
updated_at: 2026-09-17T15:29:14.291916+00:00
---
## Trigger
准备对共享远端 push（尤其直推 main）或宣称'本地领先/可快进'，而本会话内尚未 fetch 过该远端，且存在并行推进信号：运行头或时间戳晚于上次已知检查点、多远端并存指向不同仓库、或有并行会话迹象。

## Discriminator
本会话 trace 中在 push 决策前不存在对该远端的任何 git fetch——lfl/main 的值来自未知时间的旧快照；同时同会话已观察到工作区在活跃推进（部署头几分钟内从 28f7dc7d 前进到 d3f6b150，且 git remote -v 显示 lfl/origin/mainrepo 三个指向不同仓库的远端）。这两点在当时已足以判定'本地 main 领先远端（快进可推）'是未经证实的结论。

## Short path
- 复核运行态与远端拓扑（git remote -v + 各远端 main），确定活跃远端；把无法解析的旧 PR 引用识别为误引而非事实。
- 先 git fetch <活跃远端> 刷新 tracking refs，再双向比较 main..<remote>/main 与 <remote>/main..main——待解未知量：本地与远端真实是领先、落后还是分叉。
- 若观察到分叉（远端有并行线、本地有独立积累）：按仓库 PR 惯例只推特性分支，并用显式 -R <canonical-repo> 创建 PR，不对分叉的 main 硬推；仅当 fetch 后确认纯领先且无保护限制才直推快进。
- push 可能因凭据交互挂起：用后台任务 + 显式 credential helper（gh auth git-credential）执行并轮询回执，而非前台 60s 超时重试。
- 分支与 PR 回执确认一致后，登记观察提醒与基线快照，停止。

## Stop conditions
- 特性分支已在远端创建成功，且 PR 回执（URL/编号）能在活跃仓库的编号空间解析。
- 本地 main 与远端 main 的关系已基于 fetch 后的新 refs 解释清楚（分叉点明确），且未对分叉或受保护的 main 执行直推。

## Verification
- push 前检查本会话 trace 中确有对该远端的 fetch 及其 ref 更新输出。
- push/PR 回执中的仓库 URL 与 git remote -v 中的活跃远端一致，PR 号在正确编号空间解析成功。
- 领先/落后判断检查了 main..remote 与 remote..main 两个方向，而非只看单向'领先'。

## Counterexamples
- 单人沙箱仓库、无并行写入，且本会话刚 fetch 过——再 fetch 是无信息动作，可直接判断并推送。
- 推送全新唯一命名的一次性分支——快进分叉判断基本不适用，fetch 的边际收益只剩凭据链路准备。
- 离线/无网络环境——fetch 必然失败，只能基于 tracking refs 行动，但须把结论标注为未验证并预置被拒后的恢复路径。
