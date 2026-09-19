---
method_id: resume-partial-reads-at-continuation-pointer-55734bc20891
name: resume-partial-reads-at-continuation-pointer
description: 一旦已知某次抓取/captured artifact 是部分的，就把已交付的范围当作“已占有事实”：从手头的 coverage/range 元数据（已占有偏移、next_start、complete 标志、blob hash）推导出未读补集，只请求这个补集。绝不重新请求已在上下文中的范围——对同一不可变 blob 的重复 hydration 只会返回哈希相同的字节，重新解决一个已解决的未知量。可推广到一切可按范围寻址的读取：分页网页证据、按 offset 读文件/日志、cursor 分页查询。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:863879fe-d8f5-48d9-bbdc-6ddc6eaf4b8b:78:263ac945697ad321e315
evidence_refs: learning:learn:182f928c3056
created_at: 2026-09-19T03:26:44.034650+00:00
updated_at: 2026-09-19T03:26:44.034650+00:00
---
## Trigger
某次抓取返回部分内容（coverage 形如 text_char:0-N/source_partial、complete=false、有续读指针），且下一步需要读取同一份已捕获证据的剩余部分（目标事实已知位于“被截断的中间段”）。

## Discriminator
决策当时已可见：前 4000 字符已完整出现在上下文中，且是同一个不可变 blob（固定 blob_sha256）的前缀，未读部分严格从续读点（next_start=4000）开始；因此唯一未知量是 [4000, end)，从 0 起读无法缩小该未知量，只能重复交付已占有、哈希相同的字节。

## Short path
- 抓取源；若 range 元数据显示 complete=true，停止发现，直接进入分析。
- 若为 partial，记录已占有范围与续读指针（next_start / complete / blob hash），把未知量精确定义为未占有的后缀。
- 后续读取从 next_start 发起——绝不从已在上下文中的偏移（如 0）重新开始。
- 沿每次响应的 next_start 链式推进直到 complete=true（本例 4000→8000→末尾即完成）。
- 对拼合后的全文核验目标事实，把结论绑定到 blob/range 哈希，产出交付物后停止，不再回读。

## Stop conditions
- range 元数据报告 complete=true，或全部目标事实已在已交付范围内定位并核验。
- 续读链断裂（未 complete 却无 next_start）：改用显式边界探测，而不是从 0 重读。

## Verification
- 任何范围不被交付两次：每次响应的 start ≥ 上一次的 next_start；已占有前缀的 range_sha256 不再重现。
- 每个请求的 start 等于上一响应的 next_start；所请求范围的并集恰好等于缺失集。
- 最终结论只引用本次实际交付的范围，并绑定同一 blob_sha256。

## Counterexamples
- 对易变的 LIVE 源做刻意的时效性复核：稍后重取同一范围正是目的，不是摩擦。但此理由对重放不可变 evidence store 不成立——hydration 读的是同一 blob，“复核”不增加任何信息。
- coverage/偏移元数据缺失或不可比（例如旧片段由不同抽取器生成、字符偏移不对齐）：指针法不适用，只能重读或探测。
- 先前片段本身可疑（传输失败、哈希不匹配、中途截断）：从 0 重读属于合法修复，不是冗余。
- 若传输 API 本身强制首次 hydration 必须整段读取，则该成本是环境强制的；方法从第二页起仍然适用。
