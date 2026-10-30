---
method_id: range-bisect-tail-anchor-on-noisy-receipts-2eb7b0b3bcbb
name: range-bisect-tail-anchor-on-noisy-receipts
description: 长回执区间续读的导航策略：当可见首段被无界噪声数组占满、range 游标支持任意 start、回执无总长字段时，不重读已见窗口、也不顺序 next_start 扫完全文，而是向前跳跃，用 count=0 且 complete:true 的空窗口钉住 blob 末端，再回退一窗读尾部终态块（如 stage_facts），前一窗取 per-target live/stable（pid/git_head/generation），互证即停。适用于该回执就是指定权威面的裁决场景（磁盘同名字段会给出陈旧回声、或按 target 定点重查不可用时）。
aliases: 长回执跳读尾部找终态, 噪声数组占头怎么跳读, 回执别从0重读直接跳, 空窗口定界再回退读尾, 截断回执二分找目标段
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e827e946-e151-4ded-9bdf-58c042570992:278:9c79a2b29cf2d189cd5b
evidence_refs: learning:learn:cf2ba432806c
created_at: 2026-10-30T21:26:41.916536+08:00
updated_at: 2026-10-30T21:26:41.916536+08:00
---
## Trigger
核验类任务需从一条很长且 range 标 complete:false 的权威回执中取 per-target 裁决字段，但可见首段全为与未知量无关的历史噪声（如旧代次 audit/lag 数组），且无更窄的定点查询可用或磁盘同名字段会给出陈旧回声

## Discriminator
回执游标元数据（count/applied_limit/next_start/complete）加上可见窗口内容：所需字段不在已见窗口内、噪声数组长度未知、任意 start 可用 ⇒ 顺序续读成本随 blob 线性增长且重读 start=0 必为浪费——首次续读应从可见截断点之后开始

## Short path
- status 首读：确认可见首段只含噪声且 complete:false，未知量=未读段中的 per-target 终态/版本字段
- 续读同一 evidence_ref 时永不从 0 重读：从截断点之后或约半 blob 量级向前跳跃
- 窗口仍落在噪声数组内→继续向前探测；得到 count=0 且 complete:true 的空窗口即 blob 上界
- 从上界回退一个窗口读尾部终态块（如 stage_facts），再回退一窗读 per-target stable/live（pid/git_head/matches_desired_generation）
- 尾部终态与 stable/live 的 action_id/generation 互证一致，对齐 desired 后即停并回报（范围外附带事实单独标注）

## Stop conditions
- 尾部终态块与 per-target live/stable 字段均已取得且 action_id/generation/git_head 互证一致
- 可见首段本身已含裁决字段（如非空 admission barrier/终态屏障）→ 无需任何续读
- 控制面提供按 target 定点重查且更便宜 → 改定点调用即止，不做区间导航

## Verification
- 空窗口(count=0, complete=true)确认到达末端；回退窗口应含闭合的 JSON 尾结构而非数组中段
- 各 target stable.generation/git_head 与尾部终态块的 action_id/status 对齐
- 最终结论与 desired 对齐成『想跑 vs 实跑』；范围外发现（如仍落后代次的其他端）标注为附带事实而非异常

## Counterexamples
- 回执一两个窗口内即 complete:true → 直接读完，跳跃/二分反而多花调用
- 裁决字段就在可见首段（barrier 非空、终态失败码）→ 首段已可裁决，续读是浪费
- 传输层只有顺序 next_start 游标、不支持任意 start → 本方法不适用
- 存在更新鲜更窄的权威面（按 target 定点重查、已核对 pid/started_at 一致的当前磁盘 manifest）→ 优先该面，不在长回执上做区间搜索
