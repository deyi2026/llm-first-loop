---
method_id: aggregate-restart-audit-per-service-generation-lag-13783f6c3498
name: aggregate-restart-audit-per-service-generation-lag
description: 用户报告『已重启/已部署（含 target=all 聚合操作）』后审核运行面时，不要把聚合回执的成功标志或 coverage 字段当作全部目标已收敛：以回执内按服务/目标的行级 generation（或版本指纹）比对为准——收敛目标应带 verified_generation==desired 且 effective_lag=0；lag>0 且无 verified 行的目标是真实漂移，需单独 restart 并按 action_id 查终态。回执 note 常自声明『批外目标只是整单记账、标志只反映最新回执行』，这类自述语义优先于标志位。收尾把覆盖盲区固化为机械改进建议（纳入物理批或自动级联单重启），而非仅人工补救。
aliases: 重启完还有服务跑旧版本, restart all 漏了服务怎么查, skipped_by_design 是没重启吗, 按服务 generation 核对重启生效, 整批部署后逐服务对版本, 部署回执 uncovered_services 处理
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fb85cea0-beb4-424d-b482-2819180ee46f:3353:dbb41bd73fc9ef76f019
evidence_refs: learning:learn:7c06e3bcf46c
created_at: 2026-11-11T12:35:33.830052+08:00
updated_at: 2026-11-11T12:35:33.830052+08:00
---
## Trigger
用户/上游声明聚合重启或部署已完成（如 restart target=all、整批 deploy）并要求审核、验证生效或给健康建议；部署/服务状态回执中出现 physical_batch、uncovered_services、skipped_by_design、generation_lag 等覆盖与收敛字段。

## Discriminator
部署回执 audit_summary 的按目标行级差异：收敛目标带 effective_lag_generations=0（或 verified_generation==desired、verified_outcome=ok）；漂移目标 lag_generations>0 且无 verified 行。coverage/skipped 标志只是最新回执行的记账——此前单独重启成功也可能被更新的 all 记账翻回未覆盖，物理重启史必须由行内 generation/verify/时间戳重建，不能单看标志位。

## Short path
- 从部署状态回执钉住 desired generation/git_head 与 physical_batch 名单，不做全仓/全进程宽枚举。
- 逐行比对 audit_summary：每个目标 live generation/git_head 对 desired；effective_lag=0 即已收敛。
- lag>0 且无 verified 行、又不属于设计保留的目标→单独 restart；参数缺失时按拒绝回执/合同一次性补齐（含 target）。
- 按 next_check 查该 action 终态（status 按 action_id），直到 succeeded 且收敛判定不再列出该目标。
- 全部目标 effective_lag=0→宣布收敛；同时把『批外目标漏物理重启』写成机械改进建议（纳入物理批或自动级联单重启）。

## Stop conditions
- 部署回执中每个目标的 live generation/git_head 均等于 desired（无 lag 行、effective_lag_generations 全为 0）
- 补发 restart 的 action_id 已查到 succeeded 终态且该目标退出 lagging/convergence 名单

## Verification
- 按 action_id 查 status 终态为 succeeded，且 status 回执的 convergence/lagging 不再包含该目标
- 重读部署状态回执逐行核对：每目标 matches_desired、git_head==desired；不依赖 coverage/skipped 标志位

## Counterexamples
- 单目标部署或回执只有一个 target：无聚合覆盖盲区，直接核对该目标的 action 终态即可
- 某目标 lag 是设计意图（灰度钉旧版、金丝雀保留旧代）：漂移是安排而非故障，标注说明，不自动重启
- 回执无按目标的 generation/版本明细、只有聚合布尔成功：行级判别器不存在，改用每目标进程启动时间/产物指纹等端点证据
