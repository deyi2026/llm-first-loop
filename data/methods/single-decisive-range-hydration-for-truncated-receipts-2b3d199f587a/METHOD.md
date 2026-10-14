---
method_id: single-decisive-range-hydration-for-truncated-receipts-2b3d199f587a
name: single-decisive-range-hydration-for-truncated-receipts
description: 当权威工具回执被截断、以分页 evidence hydration 传输，而用户只需其中少数结构化字段（如各服务收敛终态）时，先用回执自带 range 元数据决定读取宽度：applied_limit==requested_limit 且 bounded_by_server_max=false 表明页宽是自选、未被服务器封顶，应一次请求覆盖全 blob 的大 limit；若被截，再按首屏已见顶层结构（无关审计数组在前、状态块在后）定向跳读目标区段。不要用任意小页宽顺序或跳页扫描长回执。本集验证三服务重启收敛：status 之后用 100 字符探针加 4 次 4000 字符跳页（留下多处未读 gap）搜寻 stable 块，1-2 次决胜范围读取即可完成。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1897dc0c-c278-413c-b54d-22c50b97372f:1964:6508f140d74f948d5447
evidence_refs: learning:learn:5877b8d9a9e5
created_at: 2026-10-14T14:08:26.772809+08:00
updated_at: 2026-10-14T14:08:26.772809+08:00
---
## Trigger
权威工具回执（status/runtime snapshot 等）被截断或以分页 evidence hydration 传输，且所需答案只是回执中少数结构化字段（终态/收敛/门控标志），而非全量内容

## Discriminator
回执 transport 元数据显示 applied_limit==requested_limit 且 bounded_by_server_max=false（页宽自选、服务器未封顶），且首屏已揭示 blob 顶层结构，可定位目标字段所在区段（如长 audit/generation_lag 历史数组在前、per-service stable 状态块在后）

## Short path
- 先做一次权威实测调用核验异步终态（不凭记忆），得到截断回执与 evidence ref
- 读回执 range 元数据：页宽是否自选、是否被 server max 封顶、next_start/complete 边界
- 未被封顶则一次请求 start=0、大 requested_limit 覆盖全 blob；若被截则按已见结构跳过无关数组，定向一次取目标区段
- 在已取回文本中解析目标字段（stable generation、restart_required、pid、succeeded_at），与 desired 逐字段对齐
- 确认引用字段均落在实际取回的字符区间后作答并停止

## Stop conditions
- 目标字段已从同一 blob（blob_sha256 一致）的实际取回区间读出，并与用户问题对齐
- 首屏回执已含足够答案时，不做任何 hydration

## Verification
- 每次读取核对 range 元数据（applied_limit/count/next_start/complete/range_sha256）；最终引用字段所在字符区间必须在已取回范围内，未读 gap 中的内容不得引用
- 结论以带时间戳快照表述，与 desired generation/发布头逐字段比对后停止

## Counterexamples
- 用户问题只需首屏已显示的字段（如 admission_barriers 为空）→ 首答即止，任何翻页都是多余
- blob 是无结构流式日志且 bounded_by_server_max=true 真被分页约束、目标位置无结构线索 → 顺序或二分翻页才是合理策略，不适用一次大范围读取
- 用户要的恰是长数组本身（如 lag 历史/审计明细）→ 不应跳过数组直取尾部
