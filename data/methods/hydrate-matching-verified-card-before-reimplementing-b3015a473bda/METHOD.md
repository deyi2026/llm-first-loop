---
method_id: hydrate-matching-verified-card-before-reimplementing-b3015a473bda
name: hydrate-matching-verified-card-before-reimplementing
description: 当任务明确要求先查参考（避免踩坑）、且记录检索已命中与目标平台+动作匹配的 verified 经验卡时，把成功水合该卡当作动手实现前的必经未知量：直接用结果里逐字打印的 stable ref（experience:<id>）精确读取；一旦回执报参数错误，按回执点名的具体约束（前缀/枚举/必填字段）读一次 schema 后单次修正重发，不猜格式变体、不重跑发现查询、更不在卡未读到时从零实现。本集 7+ 次参数失败后仍未水合出同平台发布卡，随后从零写脚本，恰好踩中该卡已覆盖的坑（data-URI 不触发真实上传、硬编码失效 devtools target 连上但 evaluate 全 None）。
status: active
source_model: workbuddy/step-5-preview
source_episode_refs: episode:1c391008-9819-4e88-92ce-117820e41b2e:332:ee01fc0e5053735ff058
evidence_refs: learning:learn:b7b59fbd57a7
created_at: 2026-10-18T20:03:18.446081+08:00
updated_at: 2026-10-18T23:33:48.231280+08:00
---
## Trigger
任务开局要求复用/查阅既有经验先避免踩坑，记录检索已命中与目标平台+动作匹配的 verified 经验卡并打印完整 stable ref，但精确水合调用失败。

## Discriminator
检索结果行已逐字打印 experience_ref=experience:<完整id>；且每次失败回执精确点名被违反的约束（invalid EvidenceRef prefix / action expected enum ['save','read_summary','read_source'] / 缺少 synopsis_ref）——规范 ref 与规范枚举当时已在手，无需再发现、无需猜格式。

## Short path
- 以命中行逐字打印的 experience:<id> 作 ref 调用精确水合；未知量：已验证发布配方的硬前提是什么
- 若回执报参数错：按回执点名字段读一次工具 schema，用规范枚举+必填 synopsis_ref 单次修正重发；不换检索词、不试格式变体、不重复同一发现查询
- 从最相关的 1-2 张卡提取硬约束（File 对象粘贴才触发真实上传、Page.bringToFront 前置、动态解析 webSocketDebuggerUrl 而非硬编码、发布后公网 URL 回读验收）作为本次实现前提
- 仅当无匹配卡、或卡内容与现场证据冲突（旧断言已被证伪）时，才从零实现或扩大发现范围
- 按线上终态回读核验后再报完成，不以编辑器内状态收尾

## Stop conditions
- 已读到与目标平台+动作匹配的卡并提取出可执行约束（实现前的停止点）
- 确认无任何匹配卡：此时宽发现才合理
- 规范格式调用仍失败：记录一次后绕行（读仓库内已验证脚本/现场验证），不在记录库上循环重试

## Verification
- 成功水合的卡与当前场景逐项对照（平台、编辑器类型、图片上传机制），冲突处以现场证据为准而非照抄卡
- 发布类任务按既有卡要求以公网终态 URL 回读核验，不以编辑器内草稿状态判定完成

## Counterexamples
- 命中卡与当前平台/动作不匹配（全新平台或编辑器已换代）：水合无增益，直接现场发现，卡仅作待证假设
- 简单一次性查询、无复用诉求且检索零命中：不需要先水合，也不应反复换词检索
- 记录库本身故障（schema 规范调用仍失败）：应绕行而非在库上反复重试
- 旧卡断言已被后续事实推翻（如曾断言某平台无编辑入口后被证伪）：不能照搬，以最新现场证据为准
