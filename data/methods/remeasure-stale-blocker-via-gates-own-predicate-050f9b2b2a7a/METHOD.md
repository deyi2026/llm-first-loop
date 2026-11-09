---
method_id: remeasure-stale-blocker-via-gates-own-predicate-050f9b2b2a7a
name: remeasure-stale-blocker-via-gates-own-predicate
description: 数小时前状态快照记录的『某门禁必拒某动作』，其判定依据落在多写者可变共享状态（lane/任务账本、refs）时，既不复述快照也不做近似复查：用该门禁自己的判定谓词对当前状态重新求值，可导入就直接调用其实现，否则逐字复刻语义（每 id 取最新 version 折叠、精确状态集、owner 比较）。近似裸计数会制造假阻塞并引出额外取证轮次；谓词放行即宣告旧理由失效，未知量转到下一个真实阻塞面（他人裁决/准入约束），而非重试被拦动作。
aliases: 之前的阻塞还在吗, 旧的拒绝理由过期了吗, 再判一次能不能过, 别直接数账本行, 快照里的拦截还作数吗
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:2223:a8eb60651463d95f6ff8
evidence_refs: learning:learn:846691a941a8
created_at: 2026-11-08T19:46:05.793306+08:00
updated_at: 2026-11-08T19:46:05.793306+08:00
---
## Trigger
早前状态快照或上轮记录声称某守卫/门禁将拒绝待执行动作（如 git push 因他人 active lane 必拒），但快照时间距当前已达小时级，判定依据是多会话持续写入的可变共享账本，且用户要求继续完成该动作。

## Discriminator
当时已可见：(1) 快照时间戳 vs 当前时间差距大（13:20 vs 19:31），而决定性数据源 lanes.jsonl 是共享账本且行带 version 字段（同 lane_id 多行并存）；(2) 门禁实现就在仓库内可读/可导入，其 docstring 与代码定义了精确判定（按 lane 最新 version 折叠、status∈{open,active,verifying,merging}、owner≠当前会话、解析失败 fail-open）。要预测门禁决定 ⇒ 唯一正确求值标准是门禁自身谓词。

## Short path
- 从快照提取被记录阻塞与其决定性数据源；用『时间差×数据源可变性』判 staleness，可变即转入重测，未知量=旧阻塞现在是否仍成立
- 优先直接导入并调用门禁判定函数对当前账本求值（当含受保护动词的探针本身会被更高层闸拦时，谓词重放是唯一安全评估）；不能调用才复刻语义，必须含每 id 最新 version 折叠，禁止裸计数
- 谓词放行 ⇒ 旧阻塞理由作废；未知量切换为『现在真正挡住的是什么』，从协调/权威面（他人待回执裁决、准入尺寸上限）取证
- 向用户并列两个时点对比（快照时 vs 实测时）及判定依据；执行权归属他人或需分段过闸时停下询问，不代执行

## Stop conditions
- 门禁自身谓词已在当前权威状态上完成求值并得到明确放行/拒绝
- 本地无法复刻门禁语义且含受保护动词的探针被上层闸硬拦 ⇒ 停止重试，升级或请示
- 新查明的阻塞已有指定处理人（非本会话）⇒ 不抢修，报告并给选项

## Verification
- 抽查同一 lane_id 的原始多行与折叠终态（如 selftest 残留 v1=active/v2=closed 折叠后不阻塞），确认无假阻塞也无假放行
- 结论同时引用快照时间与重测时间，且判定规则逐条对应门禁源码（状态集/version 折叠/owner/fail-open）

## Counterexamples
- 门禁部署在远端或运行版本与仓库源码有偏差 ⇒ 调本地实现会误判，改用非变更探针或询问真实门面
- 判定所需上下文本会话无法复现（他进程会话身份、网络凭据）⇒ 只做只读语义复刻，不伪造上下文调用
- 阻塞是不可变历史事实（对已合入内容的 REVISE 裁决、签名拒绝）⇒ 重测不会改变它，直接处理实质
- 快照仅数秒/分钟新且单写者 ⇒ 无需重测，照快照行动
