---
method_id: raise-page-size-when-limit-is-self-imposed-48949859a8ba
name: raise-page-size-when-limit-is-self-imposed
description: 对分页/范围式读取（evidence hydration、range fetch、list 分页）做全量提取时，若首个回执显示 requested_limit==applied_limit 且 bounded_by_server_max=false，说明页大小是请求方自选、服务端并未设上限；此时下一次请求应直接放大 limit 以一次取完剩余内容（服务端返回 min(剩余,limit)），而不是按原页大小继续逐页翻。本集对同一 README 连续 6 次 4000 字符 hydration，每次回执都带此字段却从未调大，多耗约 4-5 次往返；放大页大小后约 24k 字符可 1-2 次取完，信息量不变。
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:bc07ea9d-6ab9-44b7-b385-65eea54960b6:29:dd59b40f3ece0aa112ea
evidence_refs: learning:learn:d23f36a3e118
created_at: 2026-09-28T09:25:17.230371+08:00
updated_at: 2026-09-28T09:25:17.230371+08:00
---
## Trigger
任务需要从分页读取接口取整份 artifact（全量提取场景），且首个分页回执给出 requested_limit==applied_limit、bounded_by_server_max=false、complete=false。

## Discriminator
首次分页回执中的 bounded_by_server_max=false：证明当前页大小是请求方自选而非服务端强制，下一跳可通过放大 limit 折叠剩余全部翻页；配合 complete=false / coverage=source_partial 确认其后仍有内容。该事实在第一次读取回执即已可见，属 knowledge-at-time。

## Short path
- 首页用默认 limit 读取，专门检查回执的 requested_limit/applied_limit、bounded_by_server_max、complete 字段
- 若 bounded_by_server_max=false 且任务需要全文：下一次请求直接传远大于预估体量的 limit，一次取完剩余内容
- 仅当回执转为 complete=true 时停止；若转成 bounded_by_server_max=true 则回落为按 next_start 逐页翻
- 与全文读取无依赖的独立未知量（如本地基线测量）并行推进，不串行等待翻页

## Stop conditions
- 最后一次读取回执 complete=true，且已取得任务所需全部内容
- 回执 bounded_by_server_max=true：服务端强制分页，恢复按 next_start 逐页
- 任务只需局部内容且已读范围已覆盖所需章节

## Verification
- 核对最终引用的每个章节都落在已返回的 range/coverage 内
- 输出结论前确认末次回执 complete=true 或内容已到 artifact 尾部
- 横向比对：同体量 artifact 的读取往返次数应从 N 次降至 1-2 次

## Counterexamples
- bounded_by_server_max=true：上限由服务端设定，放大请求无效，必须逐页
- 任务只需要特定章节/范围：目标化 range 读取更短，整篇拉取反而膨胀上下文
- artifact 体量远超上下文预算（超大日志、全库抓包）：大页一次拉取会挤占上下文或放大成本，应按需分页、拿到所需即停
- 读取计费/限速敏感的通道，单次超大读取代价高于多次小读时
