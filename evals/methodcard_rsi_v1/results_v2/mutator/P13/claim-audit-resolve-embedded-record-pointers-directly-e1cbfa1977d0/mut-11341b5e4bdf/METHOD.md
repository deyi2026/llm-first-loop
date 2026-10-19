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
拿到一份针对本地项目/证据库的事实性断言文档需要核验时（如第三方审查、外部分析报告、评审意见），且断言中嵌入、或已由先前工具回执暴露出可解析的记录标识（日期+类型前缀+slug、文件路径、精确数字、版本号）。

## Discriminator
某条断言对应的精确权威记录标识在当时已经可见（断言文本自带日期+类型前缀+slug，或此前 ls/回执已列出确切文件名）。此时对同一证据库做任何换措辞的语义/关键词查询都严格劣于直读该记录；且约定命名的记录可能恰是语义索引盲区（本集两次 search_docs 未命中，文件名却已在目录列表中）。knowledge-at-time 成立：文件名与断言措辞均在第二次检索前已出现在回执里。

## Short path
- 先零工具分诊断言：内部可核（版本/规模/测试数/记录）/ 外部世界事实 / 主观评价，避免把不可核断言也送去检索。
- 对内部断言提取嵌入指针：日期+RESULT/PLAN/QUALIFICATION 等前缀+slug、文件路径、精确数字、版本串。
- 指针若已解析为确切路径（含此前回执已列出的），直接 read/grep 该记录核对所引数字，不再把断言改写成全库查询。
- 指针尚未可见时，最多做一次列表级动作（ls/git log）让候选记录现形，然后转直读。
- 外部断言仅在真实可达来源上尝试核验；搜索失败或垃圾命中必须输出 unverified，不得沉默接受原文、也不得反着断言为假。

## Stop conditions
- 每条断言都已归类为 verified（附记录引用）/ discrepancy（附原文引用）/ unverified，之后不再检索。
- 权威记录与断言数字冲突时立即报告 discrepancy，不需要再找变体证据佐证。
- 来源不可达且本地无权威记录时，以 unverified 收口，而不是继续换词搜索。

- Verification 未逐条通过前不结案（覆盖全部 2 条验证条目）

## Verification
- 结论表中每个 ✓ 都引用实际读到的记录（文件+表格/行），而不是来源文档自己的断言。
- 未能重新取源的外部断言被显式标注 unverified 并排除出行动依据。
- 确认被引记录确实存在于目录/回执中（不受信文档可能引用不存在的文件）。

## Counterexamples
- 无可解析内部指针的主观断言（评分、排名、成熟度判断）：本地无记录可读，只能标注为观点，不应发起检索。
- 本质外部事实（本地库不可能权威，如竞品版本/发布日期）：本方法只约束在失败后停在 unverified，真正核验需真实网络来源。
- 存在并发写者的共享记录且要下终局结论：改用 fresh-read-authoritative-record-before-finality-claim，成稿时刻重读。
- 首次探索、尚无任何指针可见时：一次有针对性的 search 是合法的；本方法禁止的是精确指针已在手时把它退化回模糊查询。
