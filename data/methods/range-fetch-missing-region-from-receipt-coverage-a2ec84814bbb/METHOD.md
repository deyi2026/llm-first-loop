---
method_id: range-fetch-missing-region-from-receipt-coverage-a2ec84814bbb
name: range-fetch-missing-region-from-receipt-coverage
description: 当读取回执显式给出总量与截断边界（总行数/总字节、显示截止点、size_bytes）时，缺失区域是可计算的，应在第一次读取后直接按回执元数据发一次 ranged/partial 读取（offset/limit 或 evidence hydration 补取尾部），而不是把同参数的全量读重发一遍。本集：第一次 read 已知截断在 L225/共253行/15826字节，模型甚至复述了『读最后28行』的正确计划，却仍重发了同参数全量读，收到逐字节相同（同 snapshot_ref/同 sha256）的回执，浪费一轮后才用 ranged hydration 一次取回尾部。收益：每个大文件任务省一轮同参重复读；更大的收益是把『下一步读取动作』改为由回执元数据确定性导出，而非凭感觉重试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:96d621f5-1690-49cb-8e4d-e05d75600791:229:655f6ac71c7c50380de9
evidence_refs: learning:learn:d2e17d7888fe
created_at: 2026-10-11T02:50:28.579834+08:00
updated_at: 2026-10-11T02:50:28.579834+08:00
---
## Trigger
一次 read 回执只返回了文件的部分显示（8192字符类上限截断），但回执显式携带 coverage 元数据：总行数/总字节 + 显示截止行（或可从 size_bytes>显示上限推出截断），且任务还需要未显示区域才能继续编辑/裁决。

## Discriminator
回执自身的 coverage 元数据在第一次读取时就把搜索空间缩成一个精确区间：总量（如 253 行 / 15826 字节）减去已显示范围（如截断在 L225 / ~8192 字符）= 唯一待取尾部（28 行），且读取通道本身已提供 ranged 取回手段（offset/limit 参数或 evidence hydration 的 recovery_handle）。此事实在重发全量读之前就已完全在握，无需任何新信息。

## Short path
- 第一次 read：取内容快照 + 回执 coverage 元数据；判断目标内容是否已在显示区内（本例未知量：L226-253 是否已含 §3 裁决与变更记录）
- 若不在：由回执元数据直接算出缺失区间（总行数 − 截断行），只发一次 ranged/partial 读取（按末尾偏移或 evidence hydration 设 start/limit），绝不重发同参数全量读
- 拼合显示区 + 取回区，确认所需段落齐全后立即进入修订动作（不再碰同文件读取）
- 编辑完成后用一次针对性 grep 验证旧措辞/旧状态词残留，收尾

## Stop conditions
- 显示区与取回区拼合后已覆盖回执声明的全部行数/字节（如 253/253 行），或至少覆盖任务所需段落
- ranged 读取已取回目标段落且修订验证通过，对同文件再无任何读取需求

## Verification
- 多次读取区间拼接后覆盖回执声明的总行数，且全程不存在参数相同的重复调用
- 收尾 grep 旧措辞（如『建议稿/待落地』类状态词）仅命中历史记录行，正文待定措辞清零

## Counterexamples
- 回执 coverage 为 complete / 无截断标记：一次读取已足够，任何第二次读取都是 post-sufficiency 浪费，本方法不触发
- 回执未声明总量或截断边界（缺失区间不可计算）：此时允许用不同参数探测（增大 limit、换 range）；方法的前提是元数据存在
- 文件存在并发写者、需要在成稿时刻确认新鲜度：重读是 freshness 需求（属 fresh-read-authoritative-record 类场景），但仍应做 targeted/ranged 读，而不是同参数全量重发
- 所需内容已完全落在首次显示区内：直接进入任务动作，零补读
