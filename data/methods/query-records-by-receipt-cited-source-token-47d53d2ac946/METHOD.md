---
method_id: query-records-by-receipt-cited-source-token-47d53d2ac946
name: query-records-by-receipt-cited-source-token
description: 需要追查一条聚合/审计回执（自评指标、状态摘要）背后的明细记录时，回执本身逐项打印的来源标签/kind（如『来源 declaration_check』『可 search_records(kind=self_eval)』）就是现成的精确检索键：直接用该精确 token 查记录库，不要先把问题翻译成带否定词的自然语言短语（『声明核验 缺证据 无支撑』）再猜措辞——中文释义与库内英文 kind 词表不匹配，会造出首轮 miss 和换词重搜。回执未印来源标签、或问题按内容语义跨 kind 时才用释义/关键词检索；若只印本地化别名，先做别名→kind 映射再查。
aliases: 回指标来源标签当搜索词, 回执里印的来源直接查记录库, 别把来源标签翻译成中文再造词搜索, 聚合回执的来源字段就是检索键
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:a6989bff-e814-43eb-9f8a-a24f42790dd9:0:1cfe707c4223a22a3f9a
evidence_refs: learning:learn:1eb86db811fa
created_at: 2026-11-05T22:20:45.612978+08:00
updated_at: 2026-11-05T22:20:45.612978+08:00
---
## Trigger
聚合/审计类回执（自评指标、状态摘要）逐项打印了数据来源标签或 kind 提示，而下一步需要取这些来源的明细记录时

## Discriminator
回执文本中逐字出现的来源 token（如『来源 declaration_check』或『可 search_records(kind=…)』）——它在任何检索调用之前就已在手，是零猜测成本的精确键；释义短语（尤其含否定词）与库内 kind 词表不匹配

## Short path
- 读聚合回执，摘出逐字打印的来源 kind/记录 ID 与检索语法提示
- 直接用该精确 token 查记录库（一次命中明细，不做释义改写）
- 把弱项/异常指标逐条对应到来源记录，解释成因
- 全部待查项有明细支撑，或精确检索为空时如实记 miss 并停止

## Stop conditions
- 每个需追查的弱项/异常都已取到其来源明细记录
- 或按精确来源 token 检索为空——记录 miss，不再连续换措辞重搜

## Verification
- 命中记录的 kind/来源字段与回执引用的标签一致
- 调用序列中不存在『释义 miss→换词重试』的模式

## Counterexamples
- 回执未打印任何来源标签/kind → 释义关键词检索是唯一途径
- 问题按内容语义跨多个 kind（如『所有提到回滚的记录』）→ kind token 过窄，应走内容检索
- 回执只印本地化别名（如『声明核验』）而非库内 kind token → 直接查中文会 miss，需先做别名→kind 映射
