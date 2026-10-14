---
method_id: calibrate-paged-read-coordinates-from-first-response-3972af26dbdd
name: calibrate-paged-read-coordinates-from-first-response
description: 分页/限长读取大文件时，首个响应已同时携带 range 元数据与带行号的内容标签；当请求坐标与内容标签不一致（相对偏移 vs 绝对行号），或工具宣称的显示范围超过实际返回内容（字符上限截断）时，先用一次恒等式校准坐标映射与有效页容量，再算术规划剩余页，避免逐次猜行号造成错页/空页重读。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:2d3fd645-2639-44ec-9f14-2a96c1c807fe:94:2a38664f69f3e41af778
evidence_refs: learning:learn:e16c796d4c0b
created_at: 2026-10-14T12:51:42.892315+08:00
updated_at: 2026-10-14T12:51:42.892315+08:00
---
## Trigger
用限长或分页工具读取大文件，且首个响应出现以下任一可观察事实：请求的 range.start 与返回内容首行行号标签不相等；或工具宣称的显示范围大于实际返回内容（被字符上限截断）。

## Discriminator
首个分页响应自带全部校准事实：offset = 内容首行标签 − range.start（本集为 coverage 起点 114，即 start:230 返回首行 344|）；页容量 = 本页 count；剩余跨度 = 文件总行数 − 已覆盖末行。恒等式 offset + range.start == 首行标签、末行−首行+1 == count 在第一次响应时即可验证，无需试错。

## Short path
- 读首页并以实际返回内容的末行标签为准确定真实覆盖（不信宣称的显示范围）；未知量=坐标基（绝对/相对）与有效页容量
- 用响应自身做恒等式校准：offset=首行标签−range.start，核对 offset+range.start==首行标签、count 与实际行数一致
- 算术规划剩余页：目标 start=期望源行号−offset（或直接沿用响应给出的 next_start），按页容量一次算出全部后续请求
- 逐页核对首行标签==offset+range.start 且与上一页末行连续无缺口，直到 complete=true/next_start=null 且到达文件末尾

## Stop conditions
- range.complete=true 或 next_start=null，且末页行号标签到达文件总行数/EOF
- 只需特定章节而非全文：目标源行区间读完即停
- 恒等式无法建立（内容无行号标签或 range 元数据缺失）→ 改读工具 schema 或换读取通道，不再猜坐标

## Verification
- 每页首行标签满足 offset+range.start 恒等式
- 相邻页行号连续，无重叠、无缺口
- 末页 count 与 complete/next_start 一致；若需全文，总覆盖行数==文件总行数

## Counterexamples
- 工具 range 参数本就是绝对源行号（offset=0，恒等式平凡成立）：直接按绝对行号分页即可，无需额外校准步骤
- 文件小于单页上限、一次读取即完整返回：无分页未知量，不适用
- 工具 schema 已明文文档化 range 语义：先读 schema 这一条权威事实优于行为校准
- 多次读取之间文件被并发修改：旧 offset 失效，须按最新响应重新校准而非沿用
