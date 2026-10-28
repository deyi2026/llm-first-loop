---
method_id: occupancy-map-before-destructive-ref-batch-77d0db9822b0
name: occupancy-map-before-destructive-ref-batch
description: 对共享命名空间（git 分支/worktree 等存在并发占用者的资源）执行成批删除或清理前，先用一条聚合查询建立『对象→占用者→洁净度』地图并按 free/clean/dirty 三档分流一次执行；对清单与执行之间被并发删除的对象跳过并报告，而非判批处理失败。本集 28 个分支未查 worktree 占用直接 tag+delete，21 个被 HELD、1 个 tag 失败，被迫补建地图重跑一轮；而首条 git status 早已显示 WORKTREES=199。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6c50a13c-1fe0-4283-ac06-c9bca4e9d637:92:49dc404d31166bb32f09
evidence_refs: learning:learn:35cfb4beddd3
created_at: 2026-10-17T00:36:36.412582+08:00
updated_at: 2026-10-17T00:36:36.412582+08:00
---
## Trigger
准备对一批可能被 worktree、其他代理或进程占用的对象（分支、worktree、共享记录）执行删除、清理等不可逆批量操作，且首次状态探查已显示环境存在大量占用者或并发写者迹象。

## Discriminator
动手前首次状态探查已暴露的占用计数：git status 输出中的 WORKTREES=199（对约 130 个本地分支）意味着多数待删分支大概率正被某个 worktree 检出占用。该数字在批处理执行前就已存在，足以把『直接 tag+删』缩成『先建占用与洁净度地图再分流』；不需要等到 21 条删除回执失败才知道。

## Short path
- 读首次状态探查里的占用计数（如 WORKTREES 数 vs 分支数）；未知量：目标对象被占用的比例有多高
- 用一条聚合命令建立 目标对象→占用者→dirty 状态 的地图（worktree list + 各 worktree 的 status）；未知量：哪些能安全处置、哪些必须挂起
- 按图单轮分流执行：无占用→tag+删；占用且 dirty=0→先移除 worktree 再删分支；dirty>0→挂起待人工确认
- 逐对象核对回执；凡在清单与执行之间消失的对象（并发代理已删）→ 核验其 tip 是否已进 main 无数据损失后，记为并发观察并入报告，不判批处理失败
- 输出各档计数与并发观察的总账后停止，不做地图之外的追加重试

## Stop conditions
- 地图显示全部目标为 free 或 clean-worktree，单轮执行完成且各档回执与地图一致
- 出现 dirty 占用或对象持续被并发改动 → 暂停该对象并等人工确认，不执行任何不可逆动作
- 目标对象的 tip 经核验已可达 main（无独有数据）→ 归档即终点，不再尝试恢复或合并

## Verification
- 每条删除/tag 回执按 TAG-OK / ARCHIVED / HELD / 并发消失 分类可点数，各档数量与地图分流数吻合
- 对并发消失对象用 ls-tree / branch --contains 核验其内容是否已在 main，确认无数据损失后写入处置报告
- 收尾重跑一次 for-each-ref / worktree list，确认最终计数与报告总账一致

## Counterexamples
- 单人仓库、无 worktree、无并发写者：占用概率近零，先建全量地图是白工，直接逐条执行即可
- 纯可逆或只读操作（仅打 evidence tag、查询、diff）：不删除任何东西，无占用问题，不需要地图
- 只处置一两个对象的一次性操作：单条命令的回执已足以判断成败，建图成本超过收益
