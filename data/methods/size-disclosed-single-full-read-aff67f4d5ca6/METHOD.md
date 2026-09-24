---
method_id: size-disclosed-single-full-read-aff67f4d5ca6
name: size-disclosed-single-full-read
description: 当 read 回执本身已披露 artifact 总行数/大小且足够小时，对同一 artifact 的多次分段读取是纯往返浪费。规则：首次 ranged read 后若还需同一小文件的其他符号，改为一次性全量读取该文件（docstring 设计、fold 实现、接口契约一次拿全）；只有回执披露体积超出行读阈值的 artifact 才继续 grep 锚定的分段读取。同时，凡要产出需符合某接口的数据，先在该接口定义处确认确切字段名再构造。可削减重复读取与反复确认循环。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:2377:530b4aadc90a203db2b6
evidence_refs: learning:learn:4822406d6d26
created_at: 2026-09-24T05:11:49.709431+00:00
updated_at: 2026-09-24T05:11:49.709431+00:00
---
## Trigger
read/grep 回执披露了 artifact 总量（如"共 356 行"）且体积在单次全读可行范围内，而任务仍需同一 artifact 的两个以上符号（正考虑发起第二次 ranged read）。

## Discriminator
首次读取回执中的总量披露事实：如 learning_journal.py 首次读 1-40 行时回执已标明"共 356 行"，reflection.py 首读即标"共 377 行"——在发起任何第二次分段读取之前，该事实已足以判定"一次全读即可覆盖剩余全部所需符号"。

## Short path
- grep 定位锚点符号并读取目标区间；未知量：计算/调用点在哪；同时从回执获得 artifact 总量。
- 若还需同一 artifact 的其他符号且回执披露总量很小 -> 对该文件发起一次全量读取，替代后续分段读取（一次拿到设计注释、核心函数体、契约定义）。
- 逐 artifact 应用同一规则；回执显示超大的文件（如三千余行的 routes.py）保持 grep 锚定分段读取。
- 在构造任何需符合接口的 payload 之前，先在全读内容中确认产出方的确切字段契约（如 card() 的 id/summary/description/status）。
- 契约全部确认后一次性实施与测试；停止发现类动作。

## Stop conditions
- 所有所需符号与字段契约均已在定义处确认，且没有任何 artifact 被重复读取重叠区间。
- 回执披露体积超过单次全读可行性：此时锚定分段读取即为终态策略，不再尝试全读。

## Verification
- 统计每个路径的读取次数：小文件至多出现两次读取（首次 ranged + 一次全读），绝不应出现 3 次以上互不重叠的 ranged read。
- 产出的每个 payload 字段名都能在读取过的定义处找到出处。

## Counterexamples
- 回执显示数千行的大文件：全读浪费上下文，grep 锚定的分段读取才是正确做法。
- grep 已给出唯一所需符号的精确行号：单次 ranged read 即可，全读只增加无关噪声。
- artifact 是追加型数据日志（JSONL event stream），只需聚合或尾部：为修计数绝不全读，应程序化 fold。
