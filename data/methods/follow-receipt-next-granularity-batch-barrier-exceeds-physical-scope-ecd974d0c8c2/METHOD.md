---
method_id: follow-receipt-next-granularity-batch-barrier-exceeds-physical-scope-ecd974d0c8c2
name: follow-receipt-next-granularity-batch-barrier-exceeds-physical-scope
description: 当 publish/status 回执的 next 字段已逐字规定执行粒度（如"逐个 service_control(action=restart, target=..., expected_generation=N)"），且已知批处理动作（target=all 类）的 admission barrier 覆盖面大于其物理执行面（uncovered_services/skipped_by_design 需单独 restart）时，照抄规定粒度逐目标发起，不要为省调用改用"批处理+补单"结构：补单目标会被批处理持有的 barrier 拒绝（"already held by operation <批处理 action_id>"），且批处理若被 deferred 到会话结束，补单将死锁至其终态。每目标一动作一 barrier 互不阻塞；被拒后停止重试补单，查批处理终态或等释放后再补。
aliases: 单独重启被all的准入锁挡住, 回执让逐个重启就别发all, all重启没覆盖的服务补不动, 批量动作占着barrier却不执行, restart all之后补单被barrier拒
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:80a9ad77-9a07-4f8b-9da4-49adb180bd96:1229:ae8d3aca5f6dbff72c2b
evidence_refs: learning:learn:48ddbe182b77
created_at: 2026-11-04T15:06:05.217269+08:00
updated_at: 2026-11-04T15:06:05.217269+08:00
---
## Trigger
控制面（publish/status/audit）回执的 next 指引已逐字规定下一步的执行粒度（逐个 per-target 动作，含 expected_generation），同时早前回执或覆盖说明已提示：批处理形态动作（target=all）的 admission barrier 覆盖面大于其物理执行面（physical_batch 之外的 uncovered_services 记 skipped_by_design，需单独 restart）。

## Discriminator
发起动作前已可观察的两条事实：(1) 最新权威回执 next 字段是否逐字规定了 per-target 粒度（"逐个 service_control(action=restart, target=...)"）；(2) 批处理动作的 barrier 持有范围是否包含它物理上不会执行的目标（barrier.services ⊋ physical_batch）。任一成立即不应选择"批处理+补单"结构。

## Short path
- 读 status/audit 回执：确定 desired vs live 漂移，并记下批处理覆盖缺口（哪些 target 不在 physical_batch、需单独 restart）
- publish 后以回执 next 字段为准：对 convergence.lagging 列表逐个发起 restart(target=X, expected_generation=N)，每目标一个动作、各持各的 barrier，不合并成批处理
- 记录每个受理回执的 action_id 与 deferred_effect；受理≠生效，deferred 的终态留给 run 结束后的唤醒/status 查询
- 会话内可完成的发布物内容核验照常做（release 目录 HEAD 与本次改动符号/调用点命中）
- 若补单已被批处理 barrier 拒绝：停止重试，查批处理 action 终态，待 barrier 释放或批处理终结后再补该目标

## Stop conditions
- lagging 列表内每个目标都有自己无 barrier 冲突的受理回执
- 发布物内容核验通过（release 目录 HEAD=desired 且含本次改动符号）
- deferred 动作已登记终态核验路径（唤醒或 action_id 级 status 查询），不再重复发起同目标动作

## Verification
- 每个单独 restart 的受理回执不含 admission barrier 冲突
- 终态查询（service_control(action=status, action_id=...) 或 view=targets）显示各服务 live generation/git_head = desired，convergence.lagging 清空
- 批处理补单路径下若发生拒绝，确认 barrier owner 的 action_id 与终态后再决定等待或补发

## Counterexamples
- 回执 next 规定的就是单一批处理动作且 physical coverage 完整时，逐个发起纯属多余调用，应直接批处理
- 批处理动作是同步短生命周期（受理即终态、barrier 立即释放）时，batch+supplement 不会死锁，拆分无收益
- 各目标共享同一个全局闸/单一 gate domain 时，拆粒度不改变阻塞结构，问题在闸域排序而非动作粒度（属 gate map 类方法的范围）
