---
method_id: guard-fail-attribution-before-broad-forensics-7179e48d8700
name: guard-fail-attribution-before-broad-forensics
description: 当守护/哨兵检查 FAIL 时，先把告警 payload 本身当首要证据：提取归因字段（被标记对象标识、与 run 的 id 重叠计数、触发行状态），把'真泄漏 vs 误报'缩成两个定向检查——在 run 工件中检索被标记 id、读取被标记 artifact 的来源元数据（channel/created_at/parent）。零重叠+外部来源即裁定误杀并落盘说明；只有归因仍模糊或重叠>0 时，才扩大到全目录/多 store 取证枚举。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8d524014-5137-4d7f-bb82-9755dd05c8b4:1502:8530d9f8ba0de283f1f8
evidence_refs: learning:learn:0378e53bc90a
created_at: 2026-09-22T16:12:09.087924+00:00
updated_at: 2026-09-22T16:12:09.087924+00:00
---
## Trigger
守护/哨兵/审计类检查 FAIL（如 suspected prod spill、污染告警），且告警 payload 已携带可归因字段（被标记对象 id、id 重叠计数）或触发行自身终态已知

## Discriminator
告警输出/JSON 在任何扩散枚举之前就已给出 sid_hits=0（被标记的生产新条目与 run 全部会话 id 零重叠），且触发行 reward=1.0、数据完好——这当时就足以把候选空间从'任意 store 都可能泄漏'缩为单一未知量：该被标记条目是否归属于本 run

## Short path
- 读 FAIL payload，列出归因字段：被标记条目标识、id 重叠计数、触发行标签；未知量：该条目是否归属于本 run
- 重叠为 0 且触发行完好 → 优先假设误报，做两个定向检查：在 run 工件（如 rows/）中检索被标记 id；读被标记 artifact 的头部/来源元数据（channel、created_at、parent_id）
- 工件零命中 + 外部渠道来源 → 裁定 benign misfire；再确认 run 完整性（rows.jsonl 行数、summary 落盘）以排除把 FAIL 误读为数据截断
- 把裁定作为说明写到告警文件旁，停止取证；不重跑、不触发修复动作

## Stop conditions
- 被标记 id 在 run 工件零命中，且来源元数据将其归属为外部/并发操作者会话 → 裁定误杀、落盘说明后停止
- id 重叠>0 或被标记内容含 run 数据 → 转入真泄漏取证分支，此时宽枚举才正当
- 告警 payload 不含任何归因字段 → 无 discriminator 可用，直接进入宽发现

## Verification
- 确认检索范围确实索引 run 会话 id（否则零命中是空洞的），并与告警自带的 sid_hits 字段交叉核对
- 确认触发行自身有完整 reward/终态记录，排除'FAIL 即数据丢失'的误读
- 裁定说明已落盘在告警文件旁，防后续审计误读为真泄漏

## Counterexamples
- sid_hits>0：被标记条目确实包含 run 会话 id，零重叠判别不成立，属真泄漏，应做宽取证定位泄漏面
- 告警只有 FAIL 结论而无 id/重叠等字段：payload 内无 discriminator，先宽枚举是必要的
- 被标记写入是设计内行为（该类行本就预期写此位置）：问题是策略而非归因，两个定向检查无法裁定
- run 工件不记录会话 id 时，检索零命中不构成误杀证据，需其他来源元数据支撑
