---
method_id: route-deleted-ref-recovery-by-reachability-class-not-fsck-80bb70f65836
name: route-deleted-ref-recovery-by-reachability-class-not-fsck
description: 误删 git 分支后，恢复方案先按对象可达性分类再选通道：被删分支若来自 --merged 存活分支，其 tip 是可达对象，fsck 的 dangling/unreachable 枚举在逻辑上必然捞不到，跑全库扫描是纯浪费；正确锚点是幸存的 HEAD reflog（分支自身 reflog 随删除消失，但 HEAD reflog 保留 checkout/merge 痕迹）与 PR merge commit 的第二父 ^2。逐锚点用 merge-base --is-ancestor 验证可达并按提交主题匹配分支名，恢复即逐条 git branch <name> <sha>，零风险可逆。只有未合并分支才走 fsck。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6c50a13c-1fe0-4283-ac06-c9bca4e9d637:84:23b93e45bd1ee970305a
evidence_refs: learning:learn:936226839797
created_at: 2026-10-17T00:15:01.902429+08:00
updated_at: 2026-10-17T00:15:01.902429+08:00
---
## Trigger
git 分支/引用被误删需要恢复，或他人/前一轮给出基于 fsck dangling 全库扫描的恢复计划、并声称『本地无 reflog、只剩 dangling 一条路』时；此时可先用一条已知事实（被删 refs 是否已 merge 进存活分支）裁决恢复通道

## Discriminator
当时已知两条事实即可坍缩搜索空间：(1) 被删的 11 个分支来自 --merged main 口径——tip 是 main 的祖先，属可达对象，按定义不可能出现在 fsck dangling 列表，1663 个 dangling 与目标无关；(2) 上一轮已实际从主仓 HEAD reflog 挖到这些分支的 checkout 痕迹，直接证伪『本地无 reflog』（死的只是分支自身 reflog）。二者把『全库扫 dangling 再按名字匹配』缩成『grep HEAD reflog + 读 merge commit ^2』

## Short path
- 第一步只解一个未知量：被删 refs 属于哪个可达性类——是否 --merged 进存活分支（一条 git 查询即可，不做任何全库扫描）
- 若已合并 ⇒ tip 可达 ⇒ 当场否决 fsck-dangling 恢复计划，不必跑；锚点改从 HEAD reflog 的 checkout/merge 行提取，PR 合入的分支直接取 merge commit 的 ^2 父
- 对每个候选 SHA 跑 git merge-base --is-ancestor <sha> <live-branch> 验证可达，并用提交主题与分支名交叉匹配定置信度（检出点类锚点标中置信）
- HEAD reflog 零命中的个别分支，转查次级 reflog（worktree 侧 .git/worktrees/*/logs/HEAD），仍不升级为全库扫描
- 恢复动作=逐条 git branch <name> <sha>（可逆）；工作树 dirty 或存在并发写者时只备好锚点清单、显式推迟写 refs

## Stop conditions
- 每个被删分支均有通过可达性验证的锚点 SHA，或被明确归入『待查次级 reflog』类，即停止挖掘
- 锚点提交主题与分支名匹配且 is-ancestor 退出码 0，不再继续精修或扩大枚举
- 不因『再确认几个』而跑任何 unreachable 对象枚举——可达类目标下它结构性地无产出

## Verification
- git merge-base --is-ancestor <anchor> <live-branch> 退出码 0，同时佐证『fsck 通道捞不到』的判断自洽
- PR merge 的 ^2 父与 HEAD reflog 中对应 checkout/merge 行相互印证（两个独立 provenance 边指向同一 SHA）
- 恢复执行前后各拍一次 git branch --list 留证，恢复操作逐条可逆

## Counterexamples
- 被删分支从未合并、或已被 squash 吸收 ⇒ tip 是不可达对象，此时 fsck dangling/unreachable 恰是正确工具，本方法『不走 fsck』的结论整体反转
- reflog 已被 gc/prune 或 gc.reflogExpire 配置极短 ⇒ HEAD reflog 这条 provenance 边断裂，需退回 fsck 或远端 refs，不能硬套 reflog/^2 锚点
- 浅克隆/单分支仓库没有 merge commit ⇒ ^2 锚点不存在；另外若恢复者对工作区有并发写风险，锚点验证虽安全，写 refs 的时机判断仍须独立评估
