---
method_id: anchor-on-self-report-then-probe-gaps-003c0af478b6
name: anchor-on-self-report-then-probe-gaps
description: When user requests a health/status check on a system exposing an authoritative self-report tool, use the self-report's healthy/status field as the primary discriminator. Skip broad internal searches after self-report confirms healthy; only probe dimensions self-report does not cover with targeted queries.
status: candidate
source_model: minimax/MiniMax-M3
source_episode_refs: episode:3b65f693-b562-4773-a72f-76d98cd53dab:0:96ffe8231c96c9be0a56
evidence_refs: learning:learn:bdbe0e1b58a6
created_at: 2026-09-17T15:38:30.845243+00:00
updated_at: 2026-09-17T15:38:30.845243+00:00
---
## Trigger
用户请求健康检查/状态快照/系统状态类查询，且系统暴露有 authoritative self-report 工具（status / monitoring / dashboard 接口）

## Discriminator
self-report 工具回执已直接给出 healthy / status / health 字段（例如 healthy=true、status=consistent、model_fact_integrity.healthy=true）

## Short path
- 调 self-report 工具，解析 healthy / status 字段
- 对照用户需求，列出 self-report 已覆盖与未覆盖的维度
- 仅对未覆盖维度（host 资源、外部依赖、历史异常、独立指标）做定向 probe
- 若 self-report healthy=true 且定向 probe 无异常，停止

## Stop conditions
- self-report healthy=true 且对未覆盖维度的定向 probe 无异常
- 用户所需事实已被 self-report + 必要 probe 覆盖
- self-report 显示 unhealthy，转入对应子系统的详细诊断分支

## Verification
- self-report 的 healthy 字段与外部 probe（host shell / 独立 metrics）结果一致
- self-report 中 healthy 字段与子模块 breakdown 不自相矛盾
- 报告中的每一行都能溯源到 self-report 或一次定向 probe

## Counterexamples
- 用户明确要求独立验证（审计、压测后、self-report 刚重启未稳定）
- self-report 工具本身处于被怀疑状态（刚出过故障或正在变更/降级）
- 用户需要历史趋势或异常历史，而 self-report 只提供当前瞬时快照
