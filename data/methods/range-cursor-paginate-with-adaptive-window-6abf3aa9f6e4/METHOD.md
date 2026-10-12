---
method_id: range-cursor-paginate-with-adaptive-window-6abf3aa9f6e4
name: range-cursor-paginate-with-adaptive-window
description: 当长文被工具按窗口截断且响应携带 range 游标元数据（start/next_start/complete/requested_limit/applied_limit/bounded_by_server_max）时：永远用 next_start 续读，不猜偏移、不重读区间、不另做发现性搜索；若 applied_limit==requested_limit 且 bounded_by_server_max=false，说明窗口是客户端自设的，应从第二次请求起倍增 requested_limit（直到 applied<requested 触到服务端上限），把 N 次串行小窗读压成少数几次大窗读；读到 complete=true 才宣称'已读全'。验证靠区间连续性与同一 evidence blob。本集教训：8+ 次固定 4000 字符窗口串行分页，窗口元数据早已表明可调。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b4651548-9342-4b65-bd99-85aba9b1f7a9:210:c9c1fa43c90b6e92a369
evidence_refs: learning:learn:3f1d3a64f65f
created_at: 2026-09-25T08:14:32.762790+00:00
updated_at: 2026-09-25T08:14:32.762790+00:00
---
## Trigger
内容抓取返回 source_partial/截断正文，且响应携带 range 游标元数据（next_start、complete、requested_limit、applied_limit、bounded_by_server_max），任务要求读完全文（全文摘要、完整核对等）

## Discriminator
第一个 ranged 响应已同时暴露三件可判定事实：complete=false 且给出 next_start（确定性后续内容存在）；applied_limit==requested_limit 且 bounded_by_server_max=false（窗口大小由客户端自设、并非服务端封顶）。这三点把'如何取全文'缩成单一动作：沿游标续读并调大窗口，无需任何额外枚举。

## Short path
- 首抓发现正文截断（来源回执 coverage 为 partial）→ 从截断点发起首个 ranged 读取，目的：确认分页协议、剩余规模与窗口上限
- 读取该响应的 range 元数据：窗口是否被服务端封顶、complete、next_start；未知量只剩'总长与可用最大窗口'
- 若 bounded_by_server_max=false，后续请求倍增 requested_limit 直至 applied<requested（探到上限即固定该窗口）；每次都严格从上一响应的 next_start 续读，绝不猜偏移
- 连续读取直到 complete=true；期间不重复已读区间、不切换到宽搜索/别的来源
- 产出前核对各段区间连续且共享同一 evidence blob，然后停止

## Stop conditions
- 末段 range.complete=true（或 next_start 缺失 / count<applied_limit，即已到文末）
- applied_limit<requested_limit 且窗口已达服务端上限 → 固定按上限窗口续读，不再重复探测更大 limit
- 用户所需信息已在已读前缀中被权威来源覆盖 → 提前停止（注意：'全文摘要/核对'类任务不满足此条，必须读全）

## Verification
- 各段 start 严格等于上一段 next_start：无重叠、无缺口，首段起点等于初始截断位置
- 所有段共享同一 evidence_ref/blob_sha256，确认 volatile 源未在分页中途变更
- 仅在末段 complete=true 后才输出'已读完全文/完整核对'类断言

## Counterexamples
- bounded_by_server_max=true：窗口由服务端固定，增大 limit 无效，方法退化为纯游标跟随，不应浪费请求去探测
- 用户只要标题或某个具体答案且首段已含权威答案：继续分页读全是 post-sufficiency 浪费，应立即停止
- 源无稳定快照且各段 range_sha/语义不连续：ranged 分页可能跨越内容变更，应改取单次全量快照而非继续按游标拼接
- 工具截断正文但不返回游标元数据：不要自造偏移反复重试，应改用显式 limit 参数或换抓取通道
