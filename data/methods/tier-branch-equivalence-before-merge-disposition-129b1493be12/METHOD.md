---
method_id: tier-branch-equivalence-before-merge-disposition-129b1493be12
name: tier-branch-equivalence-before-merge-disposition
description: 处理『一批旧分支的独有改动怎么并入 main』时，不采纳手工重放变更文件的隐含方案，也不逐分支展开合并操作。先用只读 git 信号按与 main 的等价关系分层：tip 可达（--merged）、patch-id 等价（git cherry plus=0）、树级真差异（merge-base..tip diff 统计）；patch-id 不匹配≠内容缺失，必须树级 diff 定论。各层处置完全不同：可达/等价→清 worktree 后删（可 tag 归档）；真独有→隔离 worktree rebase 到当前 main+复跑测试+走仓库自身 merge gate。同时读 main 近期提交中刚生效的治理规则，用仓库流程权威定义『怎么并入』，不自行发明流程。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6c50a13c-1fe0-4283-ac06-c9bca4e9d637:259:f3230043827bb4182065
evidence_refs: learning:learn:53b36804e80b
created_at: 2026-10-17T01:26:08.506318+08:00
updated_at: 2026-10-17T01:26:08.506318+08:00
---
## Trigger
用户询问一批落后于 main 的特性/集成/实验分支如何处置或并入，分支真实并入状态未知（可能部分内容已通过早期合并或 cherry-pick 等价进入 main），或用户隐含提出文件级重放并入方案时。

## Discriminator
首批只读命令输出即可分层的事实：(1) git branch --merged main 列表——tip 可达即零并入成本；(2) 每分支 git cherry 的 plus/minus 计数——plus=0 即 patch 等价已在 main，plus>0 仍不能定论（冲突解决/文案演进会改 patch-id）；(3) main 近期 log 中是否刚落地定义合并流程的治理规则——其提交时间与动机原文直接回答『当时为什么没并入』与『现在按什么流程并入』。

## Short path
- 一条命令列出目标分支 + main 近期提交——未知量：分支全集与是否存在定义合并流程的治理规则（顺带暴露规则生效时间线）
- 对每条分支算 ahead 与 git cherry plus/minus——未知量：哪些分支可能真有未吸收内容
- 仅对 plus>0 的分支做 merge-base..tip 树级 diff 统计（changed files/src 数）——未知量：patch-id 不匹配是否代表真实内容差异
- 按层给处置：可达或 patch 等价→清 worktree 后删分支（可 tag）；真独有→隔离 worktree rebase 到当前 main+复跑受影响测试+按仓库自身 gate 审查并入；明确否决文件级覆盖重放（会回滚 main 演进、切断 commit↔测试↔receipt 追溯）
- 每条分支获得唯一层属+对应动作即停，不逐分支展开执行，从改动最轻的族试点走通全链路

## Stop conditions
- 每条分支已被赋入唯一等价层且对应处置动作明确（含是否需 gate 回执）
- 合并流程建议已与 main 上现行治理规则文本对齐（引用规则而非发明流程）
- 未完成分层前不给任何单条分支的具体合并操作建议

## Verification
- 抽查可达/等价层分支：--merged 输出或 cherry plus=0 与结论一致
- 真独有层分支的树级 diff 非空，且文件数与 ahead commits 量级相称
- 最终流程建议引用的规则在 main 当前 log 中存在且文本一致（含生效时间）
- 确认分支是否被 worktree 占用等现场约束后再给清理动作

## Counterexamples
- 单条分支且明确从未并入——直接 rebase/merge 即可，分层筛查是纯开销
- main 被强制重写或历史改写过——reachability 与 patch-id 信号不可信，需重建等价判断
- 分支全部 up-to-date 无分叉——--merged 一步即止，cherry 与树 diff 冗余
- 用户只问某分支的功能内容本身——是内容审阅问题，不是并入状态等价性问题
