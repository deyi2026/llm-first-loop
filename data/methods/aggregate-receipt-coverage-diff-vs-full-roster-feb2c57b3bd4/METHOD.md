---
method_id: aggregate-receipt-coverage-diff-vs-full-roster-feb2c57b3bd4
name: aggregate-receipt-coverage-diff-vs-full-roster
description: 聚合动作（如 target=all）回执判 succeeded 只对其实际覆盖集负责，不等于名义名册全部收敛：先从回执逐成员验证证据提取实际覆盖集，与权威名册（lag 审计/全量服务清单）差分，lag>0 且无验证抵扣的成员即静默未覆盖者，须逐成员补救。定性缺口前先直读物理执行层的目标集定义判断排除是否有意：有意排除时改进方向是回执显式标注未覆盖成员，而非扩大执行面。
aliases: 重启 all 漏了谁, 整单成功不等于全员收敛, 批量操作成功但有成员被跳过, 被排除的成员是设计还是 bug, 聚合动作成功后补漏单个成员
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:4aea0dd4-3b3b-4874-8090-870678230df3:501:b23d27891308aa65f182
evidence_refs: learning:learn:c2ac2112edcc
created_at: 2026-11-03T08:10:54.289343+08:00
updated_at: 2026-11-03T08:10:54.289343+08:00
---
## Trigger
聚合/多成员生命周期或部署动作回执已达终态 succeeded，而同回执审计面仍列出某成员存在未清差距（generation lag>0、restart_required/live_git_head_mismatch 等逐目标标志）

## Discriminator
成员级验证抵扣的有无：succeeded 回执的 verify/验证抵扣列表里，覆盖集内每名成员都有对应核验记录；若名册成员 lag>0 且无任何 verified 抵扣，说明它不在该聚合动作的物理执行面内——整单 status 与该成员未收敛并不矛盾，整单 status 只对覆盖集负责

## Short path
- 读聚合动作终态回执时同时提取逐成员验证证据（verify/抵扣记录）的成员集合，而非只看整单 status（未知量：这单实际覆盖了谁）
- 与名册差分：找出 lag>0 且无验证抵扣的成员（未知量：谁被静默略过）
- 对该成员定点读 live 块（git_head/pid/started_at/差距标志），确认差距归属其当前进程（未知量：差距是否真是该成员 live 的事实）
- 以控制器逐目标差距标志为依据发起单成员补救（带准确期望代次），完成判据用动作终态+live==desired，而非受理回执
- 定性缺口：直读物理执行层的目标集定义，判定排除是否有意；有意→提交『回执显式标注未覆盖成员』类改进并沉淀经验，无意→修执行面

## Stop conditions
- 名册中所有成员要么有验证抵扣/差距为零，要么补救动作终态 succeeded 且 live 已达 desired、审计 lagging 列表不再含该成员
- 缺口已定性（有意/无意）且对应改进或修复项已提交，不再扩大枚举

## Verification
- 单成员补救动作 status=succeeded，且该成员 live.git_head==desired、lagging 列表不再包含它
- 聚合回执覆盖集与名册的差分为空，或每个差分成员均有已受理/已完成的补救动作 id 可查

## Counterexamples
- 回执已逐成员列出全部名册结论且无任何差距标志——不存在覆盖缺口，直接进入分析
- 某成员 lag=0、restart_required=false，只是恰好未出现在 verify 列表——缺席无害，不必补救
- 整单回执判 failed——属『整单失败≠对象失败』的防重复执行分支，本方法不适用
- 单目标动作或名册极小、可逐项直核——无需覆盖集差分
