---
method_id: review-backlog-summary-origin-receipt-then-code-symbols-c5a990b216f5
name: review-backlog-summary-origin-receipt-then-code-symbols
description: 从 state/checkpoint 续跑一批审查缺陷修复时，清单里的一句话摘要只是索引：先定位并直读承载该清单的原始回执（如合并审查回执），逐字比对确认出处；其中以结构化字段逐字记录的条目即修复契约全文，回执里仍只有一句话的条目即终局记录，不要再在 evidence/archive 库找“更全原文”（只会命中回声），而把未知量切换为代码定位：用条目点名的符号/常量/编码词在目标子系统精确 grep；涉领域语义的条目同步 grep 设计 brief 取权威表述定修复方向。
aliases: P2待修清单只有一句话去哪找原文, state里的审查遗留列表是摘要还是出处, 一句话缺陷摘要怎么落到代码行, 修审查遗留先读哪份回执, evidence搜出来都是看过的内容还要不要再搜
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:5ecfad99-3bb7-48d5-a854-2c6d3ca3727d:2877:1290cfb7c0ad0716afde
evidence_refs: learning:learn:f11510aa8576
created_at: 2026-11-08T22:22:32.093322+08:00
updated_at: 2026-11-08T22:22:32.093322+08:00
---
## Trigger
续跑/接手一批待修审查缺陷（P0/P1/P2、review findings 等），backlog 来自 state/checkpoint/goal 回执，条目只有一句话摘要且带符号/函数/常量名，动手前需要每条的精确原文与缺陷位置

## Discriminator
state 摘要清单行与某治理回执中的行（含条目枚举）逐字一致 ⇒ 该回执即原始出处；回执内以结构化字段（如 p2_items）逐字存在的条目=全文契约，而回执内仍只有一句话的条目 ⇒ 不存在更全的记录文本，摘要即终局

## Short path
- 一次 git log/status 锚定仓库与 state 一致（HEAD、tracked 脏文件数）
- 在回执目录按清单关键词 grep 定位原始回执并直读（命中已含路径行号即直读，不必再按文件名二次搜索）：verbatim 字段条目直接作为修复契约，并确认清单行与之逐字一致即出处已找到
- 对回执里也只有一句话的条目：不再查 evidence/archive 找更全文本，把未知量切换为“缺陷在代码哪里”，用条目点名的符号/常量（原子写函数名、权限 mode、编码词、身份字段名）在目标子系统精确 grep 落位
- 条目涉及领域语义（如身份字段是否可采信）时，在 docs 里 grep 该术语，取设计 brief 的权威表述定修复方向
- 逐条修复后用定向测试+既有门禁验证（有条件时做变异还原证明测试抓得住原缺陷），回到既有合并流程

## Stop conditions
- 原始回执已给出条目 verbatim 全文，且各条缺陷位置已由符号 grep 唯一落到源码行
- 逐条修复均有对应验证回执，backlog 关闭条件满足
- 发现摘要显式引用另一份尚未读取的审查制品（review-receipts、链接 id）：停止进代码，先转去读该制品

## Verification
- 修复后的行为断言与回执 verbatim 文本逐条对应，不靠摘要转述
- 每条缺陷有定向测试；有条件时 revert 定向修复让对应测试变红
- 语义类条目的修复方向能与设计 brief 的权威表述对齐

## Counterexamples
- 摘要条目显式引用另一份未读的审查制品/链接 id：存在更全原文，先读原文而不是直接进代码
- 条目为纯行为描述、不含任何可 grep 的符号/常量名：符号检索会空转，需回到审查者或原始记录
- state 清单与任何回执都不逐字一致：state 可能手写或过期，须先重验清单本身真值再谈出处
