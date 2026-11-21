---
method_id: cross-lane-write-violation-freeze-adjudicate-route-to-lease-owner-a14992c9b2b6
name: cross-lane-write-violation-freeze-adjudicate-route-to-lease-owner
description: 报告点名一个外来提交（精确SHA+分支）写入了本lane共享worktree中属于另一活跃lane路径租约的文件时，处置权在租约owner而不在本会话。先用三个只读定点探针核对：远端PR head与main未含外来提交（冲突未扩散）、共享Board给出该文件的租约owner与状态、分支HEAD==告警SHA且diff文件集==告警清单。随即冻结：共享树转只读，向租约owner投递阻塞级协调请求请其裁定（在其自己分支处理或显式所有权转移），checkpoint记录。恢复方案（owner同意后精确revert外来SHA，或从受审基线重建独立worktree→CAS绑新head→重走独立Reviewer/全量回归）全部标注待批执行；绝不reset/force push/覆盖对方lane的任何内容。worktree路径不按分支名猜，用porcelain清单按分支ref一次匹配。
aliases: 别的分支往我的工作区里提交了东西怎么处理, 多agent并行开发撞车先冻结还是先回滚, 我名下的文件被别的lane改了该找谁, 越权提交踩进别人路径地盘的协调流程
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:b81d97a3-af1f-463a-9f1f-ac9cf885c32b:602:ca77945f917edfde7875
evidence_refs: learning:learn:b92094497fa7
created_at: 2026-11-17T09:39:36.570263+08:00
updated_at: 2026-11-17T09:39:36.570263+08:00
---
## Trigger
任务或告警点名一个精确外来提交（SHA、分支名、改动文件清单）落在你所属lane的共享worktree上，且其中至少一个文件按共享Board/注册表属于另一活跃lane的路径租约（单写者约束被违反）。

## Discriminator
进入处置前已有三点可机械核对的事实把空间压窄：(1) 告警自带精确SHA与diff文件清单，实物核对只需定点log/show而非全仓调查；(2) Board/协调注册表直接给出被改文件的lane归属，谁有处置权无需推断；(3) 队列/远端显示PR head与main仍停在冲突前值，冲突尚未扩散到远端，本地冻结即可控。三者共同决定动作边界：先验证→冻结→路由给租约owner，不自裁。

## Short path
- 只读探针1（扩散面）：查合并队列与远端，确认PR head与main是否仍为冲突前SHA；未push/merge则冲突仍局部。
- 只读探针2（归属面）：读共享Board/coordination_status，取得被改文件的路径租约owner lane与其当前状态。
- 只读探针3（实物面）：不按分支名猜worktree路径，用 git worktree list --porcelain 按告警中的分支ref精确匹配一次取路径+HEAD；再定点 git log/show 核对该SHA存在且diff文件集恰为告警清单。
- 冻结+路由：向租约owner投递阻塞级协调请求（请其裁定：在其自己分支处理，或显式所有权转移），checkpoint记录冲突SHA与冻结状态；owner答复前对本lane共享树零写入。
- 产出待批恢复方案：owner同意后精确revert外来SHA恢复受审候选（或从受审基线重建独立worktree），CAS绑定新head，重走独立Reviewer与完整回归验证；全程不force push、不触碰对方lane产物。

## Stop conditions
- 三个只读探针核对完毕+协调请求已投递且有持久化回执id+冻结已声明 → 停止，等待owner答复，不再对该worktree做任何动作。
- 任一探针与告警不符（SHA不在该分支上、文件足迹超出告警清单、租约owner其实就是本lane）→ 以git/Board实况重新定性，不按告警原文继续执行。

## Verification
- 分支HEAD与告警SHA逐字一致，且 git show --stat 的文件集恰等于告警所列文件集。
- Board显示该文件租约owner≠本lane，且该owner lane仍处于活跃状态。
- 远端PR head与main均未包含外来提交（冲突未扩散）。
- 协调请求回执含持久化id，checkpoint已记录冲突SHA、冻结状态与待决owner。

## Counterexamples
- 被改文件全部落在本lane自己的授权路径集内：没有跨lane租约问题，直接常规revert/修复即可，不需要冻结与owner路由。
- 外来提交已push/merge到远端，或他人已在其上继续开发：本地冻结+revert不再是最小恢复，需远端侧revert/换基线流程。
- 告警只有模糊描述，无精确SHA/文件清单/分支名：三个定点探针无从锚定，应先做定位性发现，本方法不适用。
