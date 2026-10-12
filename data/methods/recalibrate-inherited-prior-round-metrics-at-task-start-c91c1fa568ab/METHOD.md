---
method_id: recalibrate-inherited-prior-round-metrics-at-task-start-c91c1fa568ab
name: recalibrate-inherited-prior-round-metrics-at-task-start
description: 多步任务起点处，计划里的关键数字与定性若继承自上一轮快照或建议文本（本会话未验证），必须先做有界的权威源校准——目录字段计数、knowledge_health 程序口径、usage 账本——把继承前提降级为待验证假设后再执行；口径字段与文件层字段不一致时读定义源码对表；最终报告显式修正早前误判。关键判读：evidence 检索 miss 不是'事实不存在'，而是'该数字没有会话内背书'的信号，应转向权威存储而非换措辞重搜。与 fresh-read（成稿时重读权威记录）互补：本卡约束的是执行起点的输入前提。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cbdfc9d0-6bd9-445c-a2af-0452afd6becb:23:f4efde4b44c89c3d1b11
evidence_refs: learning:learn:3c1b873e21b8
created_at: 2026-10-10T10:25:40.753404+08:00
updated_at: 2026-10-10T10:25:40.753404+08:00
---
## Trigger
恢复或接手一个多步任务时，计划中的关键指标与定性（存量数量、'prune 极稀疏'之类）来自上一轮快照或建议文本，本会话尚未验证过；底层语料是活跃可变存储（存在 lifecycle review、usage 账本等写路径）。

## Discriminator
对这些继承数字做当前会话 Evidence 检索时，回执明示'未找到匹配 …的当前会话 Evidence'，且数字来源被标注为上轮/快照——即它们没有会话内背书；真值只可能在权威存储里（对语料目录的直接计数、knowledge_health 口径定义、usage.jsonl 账本），一次有界查询即可裁定。

## Short path
- 把继承数字与定性标记为「上轮快照，未验证」，暂缓一切依赖它们的状态断言；不要再用数字串反查会话 Evidence 找出处。
- 对权威源做有界校准：对已知语料目录直接做字段计数（如 grep '^status:' 后聚合计数）、调 knowledge_health 取目录绑定与程序口径、cat usage 账本取真源；不需要 find/ls 全目录宽枚举。
- 若继承口径字段（如 legacy_unclassified/not_tracked）在文件层不存在，grep 并读定义该字段的源码，完成程序口径↔文件字段对表后再引用。
- 以校准结果替换计划前提；若与继承定性冲突（如已存在上一轮 lifecycle review），先修正定性再执行分类/prune/提案。
- 最终报告显式列出「上轮说法 → 校准后事实」的修正项，不残留未声明的旧数字。

## Stop conditions
- 权威源计数、口径定义与账本均已取得，继承前提全部完成替换或确认，即可开始执行任务本体。
- 继承数字带有新鲜会话内 provenance（本会话近期回执）且无并发写迹象，可直接使用，无需校准。
- 数字仅作装饰性引用且全量校准成本过高（海量/远端语料）——标注 unverified 后继续，不强制重算。

## Verification
- 最终报告中每个关键数字都能指认权威来源（具体计数命令、knowledge_health 输出或账本文件）。
- 基于快照的旧定性要么被显式撤回、要么被确认，不残留未对表的口径字段。
- 后续动作（存量分类、prune、提案）引用的口径与校准后口径一致，而非继承数字。

## Counterexamples
- 数字来自当前会话内的新鲜工具回执，或资源本身是冻结快照（版本化 release、归档包）——快照即真值，不应重算。
- 继承数字与任务结论无因果关系且校准昂贵——记 unverified 即可，不为校准而校准。
- 即将依据这些数字执行不可逆批量动作（批量归档/删除）时，仅起点校准一次不够，须在动作前一刻重读权威记录，此时由 fresh-read-authoritative-record-before-finality-claim 接管而非本卡。
