---
method_id: stale-deploy-checkpoint-vs-live-plane-and-commit-ancestry-closure-a7a1ffdc7375
name: stale-deploy-checkpoint-vs-live-plane-and-commit-ancestry-closure
description: 接管停滞 Goal 做部署收口时，checkpoint 里的部署中间态（'已受理未生效'、'restart deferred'）只是过时快照：先用部署控制面实况比对——当前 generation 是否已越过 checkpoint 记录、逐服务 matches_desired_generation/verify ok、无 barrier/in_flight；已越过则 deferred 动作视为已被后续链实现，不要补发 restart。再用 git merge-base --is-ancestor 把 Goal 声称的每个 commit SHA 对 deployed git_head 核祖先关系——'推送过'≠'已生效'。两项都过，才取本会话 evidence refs 走跨会话授权写 checkpoint + complete。
aliases: 接管旧goal要不要补重启, 推送过不等于生效怎么核验, 收口前查提交在不在部署版本里, checkpoint里的部署状态过期了吗, goal收口前部署生效核验
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:de5a7274-20e0-44af-8675-fc7ea4d47553:21:75c3b0c61c4b748ade70
evidence_refs: learning:learn:2d51721df609
created_at: 2026-11-03T13:38:26.572503+08:00
updated_at: 2026-11-03T13:38:26.572503+08:00
---
## Trigger
接管停滞或遗留的 Goal 并做部署收口，其 checkpoint 把部署记录为中间态（如'已受理未生效'、'restart all deferred'），Goal 文本声称具体 commit 已推送，任务图已空、剩余工作仅为部署生效核验与收口写入。

## Discriminator
checkpoint 时间戳与 owner 会话最后活动均显著滞后（小时级）且无在跑迹象；部署控制面一次查询即给出与 checkpoint 可数值比较的当前事实（generation、git_head、逐服务 verify）；Goal 声称的 commit SHA 与 deployed git_head 之间存在可机械判定的 merge-base 祖先关系。三者当时即已可见，足以把'要不要补部署动作'缩成两个可验证未知量：中间态是否已被取代、改进是否真在生效代码里。

## Short path
- 查 coordination/goal：确认 owner 停滞无并行冲突、任务图 open=0、跨会话写约束（仅 checkpoint/update 可显式授权）
- 查部署控制面实况；未知量：checkpoint 记录的中间态是否已被后续部署链取代？
- 若当前 generation 已越过 checkpoint 记录且全服务 verify ok、无 barrier/in_flight → deferred 动作视为已实现，跳过补发 restart
- 对每个声称的 commit SHA 执行 merge-base --is-ancestor <SHA> <deployed_git_head>；未知量：改进是否真包含在生效代码中
- 取本会话 evidence refs，以 cross_session=true + reason + evidence_refs 写 checkpoint 并 update_goal complete

## Stop conditions
- 每个声称 commit 均为 deployed git_head 祖先，且全受管服务 matches_desired_generation + verify ok、in_flight/barrier 全空
- 跨会话 checkpoint 与 complete 写入均返回 success（reason_code=cross_session_authorized）

## Verification
- merge-base --is-ancestor 对每个声称 SHA 退出码 0，且本地 HEAD 与部署回执 git_head 一致
- 终局写入回执确认 goal 状态已转 complete，证据引用来自本会话真实回执

## Counterexamples
- 部署实况 generation 与 checkpoint 相同且 restart 仍 deferred/required → 必须补执行缺失动作，直接收口是错的
- 声称 commit 推到未合并分支或已被 revert → 祖先判定 NO/需追加 revert 检查，收口不成立
- Goal 交付物是运行时配置、数据或外部系统状态而非 git commit → 祖先核验不适用，需换对应真值面
- owner 会话仍在活动（未停滞）→ 不构成接管前提，先解决并行推进冲突
