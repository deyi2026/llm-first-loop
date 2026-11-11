---
method_id: sha-named-goal-adjudicate-patch-equivalence-not-ancestry-bd5d74b39e56
name: sha-named-goal-adjudicate-patch-equivalence-not-ancestry
description: 核验交接 goal（成功判据点名精确 commit SHA 要合入 main）时，SHA 级祖先检查返回 NOT_IN_MAIN 不等于目标未完成：lane/并行分支体系常以另一 SHA 落地同一补丁。下一个未知量应是『补丁是否已等价在 main』，用 git cherry -v 的 `-` 前缀、patch-id、同主题 grep 一次闭合，而不是启动补救或开始宽枚举。goal 记录 complete + 补丁等价在 main + 权威远端与本地一致 + 协调面无在途写者，四面一致即终态闭合，停止；lane 台账叙事不是新的决策未知量。
aliases: goal显示完成但指定commit不在main, 同一改动换了sha进主线怎么核实, 先查等价补丁再判定没合入, 接力核验时commit对不上主线, 防止重复合并已落地的补丁, merge-base查不到祖先先别补救
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:7a1eba9c-28e8-4047-95ed-06f3488d1728:0:7110dfeb4f13b6a11171
evidence_refs: learning:learn:16e2b043aad4
created_at: 2026-11-11T16:20:23.014746+08:00
updated_at: 2026-11-11T16:20:23.014746+08:00
---
## Trigger
交接/核验类任务中，goal 或任务书以精确 commit SHA（『把 X 合入 main』）定义成功判据，且权威面给出混合信号：goal 记录已 complete，但 git merge-base --is-ancestor 对该 SHA 判 NOT_IN_MAIN

## Discriminator
当时已在手的两条事实：goal 记录自身 status=complete，与 SHA 祖先检查 NOT_IN_MAIN 构成张力；随后一条 git cherry -v main <goal分支> 的 `-` 前缀（等价补丁已在上游）或按提交主题 grep 在 main 命中另一 SHA，即可把『没合入 vs 换 SHA 合入』缩成单一判据

## Short path
- 读 goal 记录 + task_frontier + coordination_status，闭合『属主裁决、在途写者、队列占用』三个门控未知量
- 对点名 SHA 做祖先检查；NOT_IN_MAIN 时不启动补救，先跑 git cherry -v main <分支> + 按提交主题 grep main，回答『补丁是否已以另一 SHA 在主线』
- 等价命中后钉死权威远端：ls-remote 与本地 main 比对（left-right 0/0），回答『推送副作用是否终态』
- 需要叙事时定点读 lane 台账中该等价 SHA 的记录（status=merged + close_reason + patch-id），一次即止，不枚举 data/ 目录猎取佐证
- 四面一致 → 报告终态、等价性与补丁范围差异（树级 diff 可能大于声明 delta），停止

## Stop conditions
- goal 记录终态 + cherry 判等价在 main + 权威远端与本地 main 一致 + 协调面无在途写者/队列项，同时成立
- 或等价性被证伪（cherry 为 `+` 且主题 grep 无命中）→ 才转入『目标实际未完成』分支并向用户请示授权

## Verification
- git cherry -v main <goal分支> 对目标提交输出 `-` 前缀，且命中的 main 提交主题行与目标提交一致
- ls-remote 权威 remote 的 main 与本地 main 完全一致（0/0）
- （内容级抽查）goal 声明的关键文件改动确实存在于 main 当前树

## Counterexamples
- 验收判据显式要求该精确 SHA 本身（签名 tag、审计直接指向该提交）：补丁等价不满足目标，须走原分支合并或修订判据
- 等价提交事后在 main 被 revert：patch 曾在场 ≠ 结果仍在，须以当前树内容复核
- 等价提交捆绑了 goal 之外的改动（树级 diff 大于声明 delta）：只能断言『goal 的 delta 已被包含』，不得断言两提交等同
- 属主会话仍活跃并持有队列 slot：先过 liveness/ownership 门，等价性检查不能替代（另卡职责）
