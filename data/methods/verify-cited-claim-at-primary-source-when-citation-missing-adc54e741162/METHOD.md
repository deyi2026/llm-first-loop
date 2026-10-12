---
method_id: verify-cited-claim-at-primary-source-when-citation-missing-adc54e741162
name: verify-cited-claim-at-primary-source-when-citation-missing
description: 当上游简报/顾问建议以一份具名权威文档（审计报告、风险排序）作为行动依据，而该文档经两个独立检索层确认缺失时，把『断言』与『引用』分开处理：断言若可在主源（代码/数据/日志）直接核验，就用一次定位+一次读取闭合真值，把缺失引用降级为最终报告中上报的 provenance 失实；不要继续在引用层换关键词枚举。断言核真→行动依据不变继续；核假→推翻或重定计划。本方法替换的是『找不到被引文档就无法动手』的默认假设。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ae8c5d92-6fe9-45af-bd9c-ef4912bb21e4:1457:80216fe2490cb1dcc0b6
evidence_refs: learning:learn:27bf5380c250
created_at: 2026-10-08T11:21:34.284635+08:00
updated_at: 2026-10-08T11:21:34.284635+08:00
---
## Trigger
外部输入（用户转述的建议、goal 描述、上游简报）以一份具名文档/报告作为某风险或排序结论的依据；对它的索引检索（search_docs）与精确文件名 pattern 检索均显式 miss；而断言涉及的主体（模块/类/数据面）已可通过内容搜索定位到主源文件。

## Discriminator
两个独立检索层已回执确定性 miss（回执明说『未命中/无匹配』，非超时非降级），同时主源路径已在手（本集：search_files 命中 class BackupStore → src/llm_loop/recovery/backup.py:72）。此时断言真值完全不依赖缺失文档——一次 read 即可核验（save_archive 裸 write_text、mark_recovered 裸 RMW 是否存在）。任何再换关键词找文档的动作都是在引用层扩散搜索空间，而断言层一步即可闭合。

## Short path
- 用断言主体做一次内容/符号搜索，拿到主源文件路径（本集：class BackupStore → backup.py:72）
- 对被引文档做一次精确文件名 pattern 检索；回执『无匹配』后引用层即闭合，停止换词重试（至多一次宽松列目录如 AUDIT-* 确认非改名存放）
- 读取主源，直接核验断言真/假（本集：裸 write_text 与裸 RMW 属实 → 风险为真）
- 以主源事实继续原计划（迁移范围、验收口径），把『引用失实 + 替代核验方式』写入最终报告
- 计划中若含仅依赖该文档的判断性内容（如排序推导），显式标注其来源是简报转述、未独立证实，或回退为要求补文档

## Stop conditions
- search_docs 与精确文件名 pattern 两层均显式 miss 且主源已定位 → 停止文档狩猎，转主源核验
- 断言在主源核验出真/假后立即回到行动决策，不再追加与断言无关的文档检索
- 宽松列目录确认非改名存放后，引用层关闭，只剩断言层待核

## Verification
- 最终报告包含两条可审计事实：被引文档不存在（写明检索方式与 miss 回执），断言由主源直读证实（写明文件/行为，本集 backup.py 的裸写路径）
- 逐条检查后续行动依据：每一项均可追溯至主源事实或简报中独立给出的陈述，无一依赖缺失文档

## Counterexamples
- 断言内容只存在于文档、主源无法核验时不得套用：如审计方法论、R1 排序的推导过程、威胁模型上下文——文档缺失=依据缺失，应要求补文档或重新排序，而不是拿局部代码事实顶替整份审计结论
- 检索 miss 未经二级确认不得当作『不存在』：若回执提示索引降级/过期或 recent-docs 列表明显陈旧，先做一次文件系统直查再下结论
- 简报多处引用对不上、或其他关键事实也开始失实时，问题升级为整份简报可信度：应重新索要来源或重定计划，而非局部修补单条引用
