---
method_id: evidence-index-direct-hydration-on-ref-rejection-ab5570e5e33a
name: evidence-index-direct-hydration-on-ref-rejection
description: 证据门拒绝引用或需为既有结论补引用时，不要对 evidence 库反复换措辞做 search_evidence，也不要引用未验证的 ref。直接回到已取得的 list_evidence 索引行：按 source 元数据（tool_name、label、acquired_at）把每条待证主张匹配到具体 ref，逐条以足够 range（如 1200 字符，避免 40 字符碎片）一次性 hydrate，用回执内容（提交哈希、κ、文件清单）确认后再引用。格式类 gate（如 spec_archive 缺 result_doc/merged_docs）则直接补声明字段即可。这把"在全部 Evidence 里模糊找"缩成"按索引元数据匹配个别 ref 并直接 hydrate"。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:abda90a9-c633-4664-b777-2ef993c8f7d9:626:4c221417fd6ce3a88f76
evidence_refs: learning:learn:a6a106120396
created_at: 2026-10-06T01:54:57.416985+08:00
updated_at: 2026-10-06T01:54:57.416985+08:00
---
## Trigger
终局/验证类 gate 拒绝了自报的 evidence_refs（unsupported_ref / evidence_below_threshold），或需要为一条既有结论（git 提交回执、评分裁决等）补齐本会话可验证的证据引用；且 list_evidence 已返回带 source 元数据的索引行。

## Discriminator
重试前索引行已把 ref 与来源绑定：evidence://v1/12db7c… 标注 source=execute_command:command#04c5b45fd3d4，另有 present_files、edit_file=iq_R1_notes.md 等行——ref 本身就是 hydration handle，按元数据即可匹配主张，无需全文检索；gate 回执也明确只拒了哪些 ref；首次 hydration 回执的 complete=false/count=40 表明 range 不足，不能作为验证依据。

## Short path
- 读 gate 拒绝回执，列出被判 unsupported 的具体引用/主张
- 对照手头 list_evidence 索引行，按 source 元数据匹配主张↔ref（提交回执↔execute_command 行、交付回执↔present_files 行）
- 对每个入选 ref 一次 hydrate 且 range 足够（如 1200），确认 complete=true
- 仅引用已 hydrate 且内容锚点与主张一致的 ref 重过 gate
- 对格式类 gate（spec_archive_missing）用已知文件路径（search_files 已命中 IQ-RESULT.md）补齐 result_doc/merged_docs 声明，不再补证据

## Stop conditions
- hydrate 内容包含主张锚点（提交哈希 0bf74d5dd、κ=1.0、created files 清单）
- gate 状态由 blocked 转 success，或明确只剩人工 waive 一途

## Verification
- 引用的每个 ref 在本会话至少成功 hydrate 一次且 range complete=true
- hydrate 内容中的关键字段与被支撑主张逐项一致后才写入终局声明

## Counterexamples
- 索引里根本没有匹配该主张的 source 行——说明证据从未产生，应重跑产生证据的底层动作（如真正执行 git commit），而不是翻找旧库
- gate 拒因是声明格式（如 spec_archive_missing），补字段即可，hydration 不解决该类拒绝
- evidence 库极大且 source 元数据不足以区分候选（数十条同质 observation 行）时，应先做一次受控的元数据过滤而非逐条 hydrate
