---
method_id: aggregate-restart-coverage-not-label-verify-and-restart-uncovered-target-e2ea4203a215
name: aggregate-restart-coverage-not-label-verify-and-restart-uncovered-targets
description: 聚合控制动作（如 restart target=all）的语义全集不等于物理执行面：权威状态回执的 coverage 段把 physical_batch 与 skipped_by_design 的 uncovered_services 记账行分开写。验收收敛时应逐对象对齐 live.generation/git_head 与 desired，凡 uncovered 且仍落后的对象单独补一次定向 restart，再按回执入口异步核终态；不要因整单回执 success 或聚合词 'all' 就宣布全部收敛，否则未覆盖对象会以 1 代差静默滞后（本集约 20 分钟后才被发现）。
aliases: restart all 之后还有服务停在旧代怎么办, 聚合重启没覆盖到的服务要单独重启, skipped_by_design 是什么 需要补重启吗, 重启全部服务后逐个核对 generation, 验收重启收敛 uncovered_services, wecom 掉队一代怎么补
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a6989bff-e814-43eb-9f8a-a24f42790dd9:1544:87ddbb2f4758de874d0e
evidence_refs: learning:learn:0949fb1f9242
created_at: 2026-11-06T09:47:55.242666+08:00
updated_at: 2026-11-06T09:47:55.242666+08:00
---
## Trigger
刚执行过聚合控制动作（restart target=all 一类）后核验收敛/生效，或用户报告『已重启』后的整体验收：不能把聚合目标名当作物理执行全集。

## Discriminator
权威状态回执自带 coverage 段：physical_batch 才是真实物理执行面，uncovered_services 只是 skipped_by_design 的整单记账行；且 per-target 字段（matches_desired_generation / live.git_head / restart_required）逐对象给出与 desired 的差距。『all ≠ 物理全集』这一事实已在回执中显式写明，无需考古即可裁决。

## Short path
- 验收时不看整单 success 或聚合目标名，逐对象对齐 live.generation/git_head 与 deployment desired
- 读 coverage 段：对 uncovered_services 中仍落后 desired 的对象，逐个单独派发定向 restart（target=<对象>, expected_generation=desired），参数按回执/失败回执声明一次性补全
- 受理≠完成：按受理回执的 next_check 入口异步查终态（action.status=succeeded 且 live.git_head=desired）
- 全部对象 matches_desired_generation=true、lag 清空、无 admission barrier 后才宣布收口

## Stop conditions
- 每个服务 matches_desired_generation=true 且对应 action 终态 succeeded、verify_outcome=ok
- generation_lag=[] 且 in_flight=[]，补启动作已查到终态而非仅受理

## Verification
- 重查 status：此前 uncovered 且落后的对象已不在 convergence.lagging，其 stage_facts 行 status=succeeded、verified_generation==desired
- 注意 coverage 标志只反映最新回执行：对象此前单独重启成功后若出现 newer 的聚合记账行，标志会翻回 skipped——重建物理重启史须结合行内 verify/时间戳/pid，勿单看该标志

## Counterexamples
- physical_batch 恰好等于全部对象且均已对齐 desired → 无需任何补启，直接收口
- uncovered 对象虽标志 skipped，但 live 代次已等于 desired（此前已单独重启过）→ 不重复重启，用行内证据佐证即可
- 单对象定向 restart（target=<单个服务>）无 coverage 语义 → 不适用本方法
