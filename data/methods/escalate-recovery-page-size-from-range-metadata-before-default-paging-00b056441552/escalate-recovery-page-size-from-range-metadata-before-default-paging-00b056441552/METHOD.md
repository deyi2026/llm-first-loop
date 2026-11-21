---
method_id: escalate-recovery-page-size-from-range-metadata-before-default-paging-00b056441552
name: escalate-recovery-page-size-from-range-metadata-before-default-paging
description: 异步子代理回执标注截断、需经 recovery/evidence 句柄补读全文时，不要按默认小页一页页磨。第一页回执自带 range 元数据（applied_limit、next_start、complete），它就是页大小的判别器：一旦显示默认页远小于已知内容规模且 complete=false，下一次调用立即显式带大 limit（接近服务器上限或与内容量匹配），按 next_start 大页推进直到 complete=true，并用各页 blob 哈希一致性确认是同一对象。把恢复成本从 O(内容长度/默认页) 压到 O(内容长度/最大页)。
aliases: 子代理报告被截断后怎么恢复全文, evidence hydration 分页太碎怎么办, 补读截断回执别按默认200字一页磨, 大 limit 一次拉全子代理报告, recovery handle 续读页大小怎么定
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:887a61e0-7491-47ca-a0e9-ee372f3c4656:0:3f3ec68058ea0b11c210
evidence_refs: learning:learn:be44af9c7e96
created_at: 2026-11-17T18:30:11.346072+08:00
updated_at: 2026-11-17T18:30:11.346072+08:00
---
## Trigger
一个带范围读取的产物（截断的子代理 result、bounded read、recovery handle）返回 complete=false 且需要全文，而第一页回执显示 applied_limit 远小于已知内容规模（如结算信息 tokens_out 上万、报告含多节表格）。

## Discriminator
第一页回执的 range 元数据本身就是判别事实：requested_limit=applied_limit=200、complete=false、next_start=200，同时结算回执已可见 tokens_out≈18519 ⇒ 按默认页续读需要 ~20+ 次调用；此事实在第二次读取之前就已存在，足以决定立即放大 limit。

## Short path
- 结算回执标注截断时，取回执给出的 recovery handle（evidence:// ref）作为唯一寻址入口
- 第一页只用于探测页参数与内容规模：读回执的 range 元数据（applied_limit/next_start/complete）和已见正文开头
- 若 applied_limit 远小于内容规模且 complete=false，第二次调用就显式带大 limit（接近服务器上限或匹配内容量），不再沿用默认值
- 按 next_start 大页推进，直到 complete=true；期间核对各页 blob_sha256 完全一致
- 拼合全文后立即停止，不做超出恢复目的的额外读取

## Stop conditions
- 回执 complete=true 且 next_start=null，全文已到手
- requested_limit 被服务器钳制（bounded_by_server_max 且 applied_limit 不随请求增大）⇒ 改为按服务器最大页推进而非继续放大请求
- 目标只是某个具名锚点/字段时，一次小窗口命中即停

## Verification
- 各页 integrity.blob_sha256 完全一致，确认读的是同一对象且无中途换源
- 恢复文本与首次截断回执可见的开头逐字衔接，页边界处无缺口、无重叠
- 最后一页 complete=true 才宣布恢复完成

## Counterexamples
- 回执显示 bounded_by_server_max 且 applied_limit 已是服务器上限 ⇒ 放大请求无效，只能按该页大小推进
- 目标只是锚点字段/状态行（小窗即可命中）⇒ 不要整块水合全文
- 第一页已 complete=true（内容本来就小）⇒ 无需升级页大小
- 预算或下游消费端限制单次响应体积 ⇒ 维持分页，但按最大允许页走并尽量减少往返次数
