---
method_id: exact-identity-pairing-for-event-ledger-correlation-b5ee30161d5b
name: exact-identity-pairing-for-event-ledger-correlation
description: 当需要把两个事件流/账本互相归因或配对（呈现vs声明、事件流vs usage 账本、run vs 终局），而两侧每条记录已携带精确身份键（subject_ref/declaration_event_ref/session_id/seq/run_ref）时，禁用时间窗极值（min/max）或可变前缀模糊切片做关联。逐条按 ref 配对并顺带校验序关系，账本按精确 session_id join 并用 run_ref 前缀佐证同源；任何近似口径的"命中"须复查身份字段，巧合命中改判未证实；配不上的保留 unknown，不回填 0 或取最近邻。本轮两处结论级修正（min/max 时序被早于 discovery 的声明蒙混；episode_ref 前缀切片属巧合命中）同属这一机制。
status: candidate
source_model: workbuddy/hy4-preview
source_episode_refs: episode:e3d65611-a839-42fc-bf6f-fae957ddf6cf:408:e0749f56713011b98809
evidence_refs: learning:learn:1f3bbf736933
created_at: 2026-10-15T01:11:28.418936+08:00
updated_at: 2026-10-15T01:11:28.418936+08:00
---
## Trigger
要把两组事件/账本记录互相归因、配对或投影（如 presented vs declared、事件流 vs usage 账本、run vs 终局事件），且即将编写配对/join 逻辑时

## Discriminator
配对前先检查两侧记录是否已含可直接相等的身份键（session_id、run_ref、seq、subject_ref/event_ref），以及权威文档或前轮审计产物是否已写明身份语义（如 run_ref 前缀即归属 session、"不允许取最近一条当同 run 证明"）——只要精确键存在，窗口/前缀近似就只是偷懒而非必需

## Short path
- 列出两侧记录的全部身份字段，确定哪些可精确相等，作为唯一 join 键集
- 逐条按 ref 配对，不用 min/max 时间窗代表整段关系；每对顺带校验序单调性（如声明 seq 应晚于 discovery seq），冲突作为显式数据质量问题上报而非静默计数
- 账本 join 用精确 session_id（run_ref 前缀佐证），不用 episode_ref 等可变前缀切片近似
- 对旧近似口径的每个"命中"抽查两侧身份字段是否真的相等，巧合命中改判未证实
- 无法精确配对的项保留 unknown，不以 0、最近邻或聚合值回填，停止条件为每个配对项都有 ref 级验证或显式 unknown

## Stop conditions
- 每个 contribution/配对项都完成 ref 级验证或显式标注 unknown
- 抽样复查确认不存在"身份字段冲突却仍被计数"的对
- 只读任务中账本 hash 前后一致、重跑输出逐字节相同

## Verification
- 反向自检：用旧近似口径（min/max、前缀切片）复算一遍，确认新旧结论差异可被逐条解释
- 每条配对输出两侧身份字段并排对比，供人审
- 对修正前后计数差异的每一条给出具体事件 ref 佐证（如早于 discovery 的声明 seq）

## Counterexamples
- 两侧数据源没有共享身份键（只有时间戳或自由文本）时，精确配对不可用，只能做带不确定性标注的时间对齐，本方法不适用
- 外部系统 ID 不稳定或会被重映射时，精确匹配会静默漏配，miss 应输出"需要映射表"而不是"无关联"
- 纯粗略体量统计、结论不依赖逐条配对时，近似口径可接受但必须显式标注为估计
