---
method_id: claim-audit-resolve-embedded-record-pointers-directly-e1cbfa1977d0
name: claim-audit-resolve-embedded-record-pointers-directly
description: 核验第三方文档对本地项目的事实断言时，断言文本和已收到的工具回执本身往往已暴露精确记录指针（RESULT-/PLAN-/QUALIFICATION-YYYYMMDD-slug 式命名、路径、精确数字、版本号）。此时应解析指针并直读对应权威记录，而不是把断言内容重新编码成语义/关键词查询去搜全库——本集语义检索对目标记录连续两次未命中，而普通 ls 早已列出 RESULT-20261007-restart-continuity-main-integration.md。同时先把断言分诊为内部可核/外部/主观三类：外部断言在来源不可达时只能标注 unverified，不得沿用来源文档自身说法充当事实。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ae8c5d92-6fe9-45af-bd9c-ef4912bb21e4:0:569acedb8b1cc4e4c3be
evidence_refs: learning:learn:6f12bacc8366
created_at: 2026-10-07T23:04:51.965934+08:00
updated_at: 2026-10-07T23:04:51.965934+08:00
---
## Trigger
启用（须全部满足）：
1. 手上有一份待逐条核验的事实性断言文档（第三方审查、外部分析报告、评审意见），目标是给每条断言落 verified / discrepancy / unverified 结论。
2. 至少一条断言满足下列之一：断言文本自带约定式记录标识（RESULT-/PLAN-/QUALIFICATION-YYYYMMDD-slug 或同族前缀+日期+slug）；引用了明确文件路径；含可与本地记录对账的精确数字/版本串，且此前 ls 或工具回执已列出同名候选记录。
3. 被引记录的权威源在本地（本仓库/证据库），本地读到的内容即可作裁决依据。

不启用（任一即转出）：
- 断言全部为无指针的主观评价或纯外部事实，本地无可对账记录。
- 尚处首次探索、无任何回执/目录可参考且断言不含可解析标识（此时先用一次有针对性的 search 建立指针）。
- 任务是文档整体语义总结或相似度分析，而非逐条事实核验。

## Discriminator
某条断言对应的精确权威记录标识在当时已经可见（断言文本自带日期+类型前缀+slug，或此前 ls/回执已列出确切文件名）。此时对同一证据库做任何换措辞的语义/关键词查询都严格劣于直读该记录；且约定命名的记录可能恰是语义索引盲区（本集两次 search_docs 未命中，文件名却已在目录列表中）。knowledge-at-time 成立：文件名与断言措辞均在第二次检索前已出现在回执里。

## Short path
0. 建立核验工作表（零工具）：三列——断言原文 | 分诊类别 | 嵌入指针（无则留空）。逐条填完再动手，后续每步只操作这张表。
1. 分诊（逐行判定）：含版本号/规模/测试数/对本地记录的引用 → internal；关于外部世界（竞品、第三方发布/状态）→ external；评分/排名/成熟度/优劣判断 → subjective，直接标“观点”，不进入后续步骤。
2. 指针提取（仅 internal 行）：按固定模式扫描断言原文——`(RESULT|PLAN|QUALIFICATION)-YYYYMMDD-<slug>`、显式路径、精确数字、版本串；提取不到指针的行记“指针缺失”，转第 4 步。
3. 直读（指针已可见，含此前回执已列出的确切文件名）：read 指向的记录；断言引具体数字时 grep/读表定位到行，把“记录值 vs 断言值”并排写入工作表；对该行不做任何 search。
4. 单次列表兜底（指针不可见时）：最多执行一次 ls/git log 级列表动作；候选文件名现形 → 回第 3 步直读；仍未现形 → 该行记 unverified（本地无权威记录），不再检索。
5. external 行：仅当存在真实可达来源（可访问的 URL/命令）时尝试一次；失败或命中与断言无关 → 记 unverified 并保留原文引用，既不沿用原文当事实，也不反向断言为假。
6. 汇总：工作表每行落一个结论——verified（附记录引用）/ discrepancy（附双方引用）/ unverified（附原因）。

## Stop conditions
- SC1：工作表每行均已写入三种结论之一（verified 附记录引用 / discrepancy 附双方引用 / unverified 附原因），此后对该表不再发起任何检索。
- SC2：任一 internal 行出现记录值 ≠ 断言值：立即写 discrepancy（引用记录位置+原文措辞），跳到下一行；不找变体证据佐证或调和。
- SC3：任一 external 行来源不可达、或本地无对应权威记录：以 unverified 收口；禁止对同一断言换词重搜。

## Verification
- [核验 SC1] 逐行检查工作表：每行恰有一个结论；每条 verified 的引用指向本次会话实际 read/grep 过的记录（文件+表格/行号），而非来源文档自身的复述。
- [核验 SC2] 每条 discrepancy 同时含两侧引用——权威记录位置与原文原句——并能读出冲突的具体值。
- [核验 SC3] 每条 unverified 被显式标注，且已从行动依据与结论正文中排除；不存在“沉默沿用原文”或“反向断言为假”的行。
- 存在性检查：每条被 verified/discrepancy 引用的记录，均能在目录列表或先前回执中找到同名条目（防不受信文档引用不存在的文件）。

## Counterexamples
- 无可解析内部指针的主观断言（评分、排名、成熟度判断）：本地无记录可读，只能标注为观点，不应发起检索。
- 本质外部事实（本地库不可能权威，如竞品版本/发布日期）：本方法只约束在失败后停在 unverified，真正核验需真实网络来源。
- 存在并发写者的共享记录且要下终局结论：改用 fresh-read-authoritative-record-before-finality-claim，成稿时刻重读。
- 首次探索、尚无任何指针可见时：一次有针对性的 search 是合法的；本方法禁止的是精确指针已在手时把它退化回模糊查询。