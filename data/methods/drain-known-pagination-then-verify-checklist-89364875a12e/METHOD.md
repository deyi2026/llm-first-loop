---
method_id: drain-known-pagination-then-verify-checklist-89364875a12e
name: drain-known-pagination-then-verify-checklist
description: 对带分页元数据的只读证据源核对一份预枚举事实清单时，首个截断 envelope（range: next_start、applied_limit、complete、bounded_by_server_max）已机械宣告剩余总范围；bounded_by_server_max=false 说明截断是客户端自设 limit 而非服务端上限。此时应一次并行发出全部后续 range 请求（或直接调大 limit）取全文本，再对照完整文本逐项核对清单；而不是每轮按'当前缺哪个数'串行翻一块、反复更换子目标。本集该源共串行翻页约5轮，反事实可缩为1轮并行 drain + 1轮清单核对，同时缩短易变网页源的暴露时间窗。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:776cbb14-cb07-4094-b621-823f4631b1b3:1:7df015f7cfa1ab3e4321
evidence_refs: learning:learn:2050006cfb0f
created_at: 2026-10-11T02:04:58.347450+08:00
updated_at: 2026-10-11T02:04:58.347450+08:00
---
## Trigger
对网页/API/大文件等分页返回的只读证据源核对多项分散事实（数字、日期、免责声明等），首个返回已带分页元数据（next_start、complete、applied_limit、bounded_by_server_max）且清单仍有未核对项。

## Discriminator
首个 envelope 显式给出 complete=false、next_start 与 applied_limit，且 bounded_by_server_max=false——即截断由客户端请求 limit 自设，剩余范围是已知可枚举空间，可在首次截断时就并行一次取完；该事实当时已可见，无需逐块串行探测。

## Short path
- 首次拿到截断结果时，先解析 range/integrity 元数据：确定块大小（applied_limit）、下一偏移（next_start），确认 bounded_by_server_max=false。
- 按已知块大小一次性并行发出所有后续 range 请求直至覆盖到位（或直接改用更大 limit 减少块数）。
- 对照拼合后的完整文本，把预枚举清单逐项映射到具体 char 区间/原文引文；查不到的项显式标记'证据不完整'，不再追加变体抓取。
- 清单全部有结论且 range 覆盖无缝后停止，进入裁决/报告。

## Stop conditions
- 清单每一项都已确认或显式标记不可查证，且最后一个 envelope complete=true（coverage 不再 source_partial）。
- 首块已满足全部清单项时立即停止，不 drain 剩余。
- bounded_by_server_max=true 或仅支持逐次游标续传时，退回串行按需推进，不强行并行。

## Verification
- range 链条连续：各块 start/next_start 无缝无跳号，末块 complete=true。
- 报告中每个核对项都能指回具体已取回 chunk 的原文；不得引用未在已取回范围内出现的数字或表述。
- 取全之后不再对同一 source 发起清单外的补充读取。

## Counterexamples
- 服务端封顶（bounded_by_server_max=true）或按请求数计费/限流：并行全量会被拒或浪费，应串行按需。
- 清单只有一个未知项且首块已回答：立即停止，继续 drain 属 post-sufficiency 浪费。
- 仅返回下一游标、无随机寻址的流式续传接口：无法并行，方法不适用。
- 需对有并发写者的资源做成稿时刻终局断言：本方法只解决'取全'不解决'取新'，应改用 fresh-read 类方法。
