---
method_id: field-driven-sufficiency-stop-on-versioned-receipt-pagination-e5fd2e32a9e9
name: field-driven-sufficiency-stop-on-versioned-receipt-pagination
description: 被截断的权威回执经版本化 evidence_ref 分页恢复时，若用户需求是封闭字段清单、且信封证明各页同属一个固定快照（同一 blob_sha256、固定 acquired_at/origin_run_generation），则用『剩余未解的点名字段』驱动补页并在字段齐全时停止：按序补页并勾销已观察字段，位置/总长不明时用一次远端偏移探测定界（count=0 且 complete=true 即末尾），收尾如实披露未读区间而非宣称完整恢复。防止把有界状态查询升级为全文通读（本集约 40KB 回执中大半是与点名字段无关的历史 generation_lag 与策略段，点名字段早已在已读页内齐备）。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:75dd97e9-faaa-4239-9eea-d368aa3cebd4:0:b3c024c5a52a212f44fa
evidence_refs: learning:learn:b6d1173b6421
created_at: 2026-10-21T12:12:10.505390+08:00
updated_at: 2026-10-21T12:12:10.505390+08:00
---
## Trigger
单一权威工具回执被截断，平台返回带固定版本标识（blob_sha256/acquired_at/origin_run_generation）的 evidence_ref 分页恢复句柄，且用户需求是封闭的可枚举字段清单（明确列出要报告哪些字段），而非开放式全量巡检或异常汇总

## Discriminator
两个当时已知的事实：(1) 各页信封显示同一 blob_sha256 与固定 acquired_at——这是同一快照的分页，部分读取不会跨版本错配，无一致性理由要求逐字读满；(2) 用户点名字段已在已读页内被直接观察到（如 admission_barriers:[] 即首屏可得），而剩余可见内容是点名清单之外的长列表值审计/策略段（历史 generation_lag、compat/gates），继续补页不消除任何剩余未知量

## Short path
- 执行用户指定的只读调用；回执截断则使用返回的 recovery handle 补页，不重发原调用
- 把用户点名字段列成未解未知量清单；按 next_start 顺序补页，每页后勾销已观察到且带页级出处的字段
- 若字段在文中的位置或总长不明，用一次远端偏移探测定界：count=0 且 complete=true 即到达末尾；命中内容则知仍在中段，据此收敛剩余读取范围
- 全部点名字段已观察即停止补页；报告中如实披露跳过区间（如历史审计/策略段落未逐字读），不宣称『已完整恢复』
- 否定性结论（某项为空/无）只对直接观察到的空值（如字段处显式 []）或覆盖完整的区段下，否则沿用 partial-coverage 否定门禁

## Stop conditions
- 用户点名的每个字段均已从本快照的具体页区间直接观察到出处
- 或信封 range 标记 complete=true 且各页已被连续消费完毕——只有此时才可称完整恢复
- 出现点名清单之外的追问（如『还有没有其他异常』）时，回到全量覆盖或明示部分覆盖

## Verification
- 逐字段核对：每个报告值能指回具体 start-range 的页出处
- 跨页 blob_sha256 一致，确认未拼接第二个快照
- 报告中未读区间被显式披露，而非以『分页恢复已完成』暗示全量已读
- 『为空/无』类结论对应直接观察到的空值或完整覆盖区段

## Counterexamples
- 用户要求开放式巡检或『有无任何异常』类全量结论——字段清单不封闭，跳读会漏报，必须读满或明示部分覆盖
- 需要对某命名实体/字段下否定存在结论而其所在区段尚未读到——不得用本卡提前停止覆盖（由 gate-negative-existence-claims-on-partial-coverage 管辖）
- 剩余仅一两页即可读完的小 blob——探测与跳页的成本高于顺序读完，直接读完更短
- 信封无固定版本标识、source 可能在分页间变化——部分读取可能拼接不一致快照，应改整读或按版本令牌重取
