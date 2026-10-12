---
method_id: range-receipt-driven-evidence-recovery-d259013dab32
name: range-receipt-driven-evidence-recovery
description: 当工具结果被投影截断、且关键字段（如对象 ref）只存在于带范围回执的 evidence blob 中时，不要按默认步长线性翻页。用范围回执元数据协商读取：若 bounded_by_server_max=false（步长是调用方自设而非服务器上限），单次放大 requested_limit 取回剩余；若存在同工件先前版本的 evidence，用其中同名对象的观测偏移作先验直接跳读。跳读命中后核对锚属性与版本号再取确切 ref；动作效果用语义锚重感知验证，回执 ok 不算完成。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:409:2bda235c951fb13278f6
evidence_refs: learning:learn:b3db9bc0080c
created_at: 2026-09-18T03:12:55.037333+00:00
updated_at: 2026-09-18T03:12:55.037333+00:00
---
## Trigger
projection.complete=false 或 search_evidence 命中目标记录但截断在关键字段（如 grounding_ref）之前，且底层存在可分页 hydrate 的 evidence blob

## Discriminator
首次 hydrate 的范围回执显示 applied_limit=requested_limit 且 bounded_by_server_max=false，说明翻页步长是调用方可调参数而非服务器上限；或同一页面/工件先前版本的 evidence 中同名对象的字符偏移已被观测到（同页结构跨版本稳定）

## Short path
- 截断发生时先 search_evidence 确认目标记录存在且唯一；未知量=关键字段在 blob 中的位置
- 首次 hydrate 后读范围回执的 complete/next_start/bounded_by_server_max；若 limit 非服务器上限，下一跳用大 limit 单次取回剩余整段，而非沿用默认步长
- 若同页有先前版本 evidence，按先前版本中同名对象的观测偏移直接跳读新版本对应区段；未知量=当前版本的确切 ref
- 跳读命中后先核对锚属性（name/role/tag）与 observed_version 一致，再采用 ref 执行动作；禁止由兄弟对象 URL 模式拼装未被观察的 ref
- 变更类动作回执 ok 后，重感知语义锚（如状态文本）验证真实效果；此锚同时为新版本 ref 的重新 ground 提供入口

## Stop conditions
- 当前版本目标记录的完整字段（含确切 ref）已被实际观察并用于动作
- 效果已由独立重感知的语义锚确认（receipt.status=ok 不构成停止条件）
- 回执 complete=true 或目标记录已完整读出，立即停止继续翻页/继续确认

## Verification
- 采用的 ref 所属 observed_version 与当前快照版本一致，跨版本、跨 mutation 不复用旧 ref
- 跳读偏移命中的记录，其锚属性与 search_evidence 命中的锚一致，防止对象顺序不稳定时错读
- select/scroll 等变更后以重观察到的状态锚（而非回执）确认事件链真实触发

## Counterexamples
- bounded_by_server_max=true：放大 limit 无效，必须分页，此时改用锚点/先前偏移选择 start
- blob 极大（MB 级）且上下文预算紧张：一次巨量 hydrate 不如锚定跳读或对半搜索
- 对象顺序跨版本不稳定（动态列表、排序内容）：先前偏移先验会错位，必须先核对命中记录的锚属性再信任
- search_evidence 片段已含完整记录（含 ref）：无需任何 hydrate，直接进入动作与验证
