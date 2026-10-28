---
method_id: field-targeted-skip-scan-on-paged-evidence-blobs-5800d16689b6
name: field-targeted-skip-scan-on-paged-evidence-blobs
description: 结构化 status/门禁回执被截断为带 range 元数据的分页 evidence blob、且可见头部被与本次裁决无关的均质历史数组（如逐代 lag/审计事件）占据时，不要从 offset 0 按 4K 线性读完：先记住数组元素模式，一次高偏移探测定总长并优先读尾段（idle/运行态等当前字段常在末尾），对采样仍匹配数组模式的区间跳步跨过，凑齐全部门禁具名字段即停止；随后按授权执行动作并用 action_id 定向核实真实终态。本集 10 次分页约 6 次耗在 lag 历史数组内，可省至 4-6 次定向读取。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:20456646-0ac3-4edc-a2bd-4583292afb10:0:3ef7637daffc0deaead7
evidence_refs: learning:learn:1e6b2e605d99
created_at: 2026-10-20T17:35:17.213066+08:00
updated_at: 2026-10-20T17:35:17.213066+08:00
---
## Trigger
结构化状态/验证回执被截断为分页 evidence blob（range.start/limit/complete 元数据），可见头部被与裁决无关的均质历史数组占据（重复元素模式），而决策只需少数具名字段（desired 代数、运行提交、屏障、idle 态等），且这些字段名已由任务/门禁预先枚举

## Discriminator
第一个分页内容本身即判别事实：(a) 整块是否全部匹配同一数组元素模式（如 {"generation":N,"lag_generations":M,"target":T} 重复）且不含任何决策具名字段；(b) range.complete=false 但未给总长——一次高偏移探测即可定长；(c) 所需字段清单封闭已知，'读够'有明确边界。三者同时成立时，继续均匀线性分页读历史数组是零决策增量的纯成本

## Short path
- 读起始分页：确认决策字段是否已在可见前缀；提取并记住历史数组的元素模式作为后续跳段判据
- 一次高偏移探测（远大于预期长度）定 blob 总长：count=0/complete=true 给出上界，回退读真实尾段——当前态字段（idle/运行态）常序列化在末尾
- 仍缺的具名字段用中点/回填跳读定位；任一分页采样开头仍匹配已知数组模式即整段跨过（步长加倍），模式断裂处才是候选信息段
- 每个门禁具名字段从其对应 JSON 键取得权威值即满足；未读的纯历史区间不再为完整性补读
- 条件零漂移才执行授权动作（update 带 code_root/expected_generation/restart_target），并用 action_id 定向 status 核实真实终态：受理回执≠生效，未生效如实报 action_id/当前状态

## Stop conditions
- 用户列出的每个门禁字段均已从 blob 对应 JSON 键读到权威值且与预期零漂移
- 任一关键字段漂移或门禁缺失：立即停止、不执行变更动作、只报告
- 剩余未读区间经采样确认全部属于已识别的无关历史数组
- 动作受理后以 status(action_id) 的真实状态（如 waiting_for_requester_exit）为终态报告，不得宣称已生效

## Verification
- 每个裁决字段的值来自其对应 JSON 键（desired deployment、processes、idle_state 等），而非从 lag 历史条目推断
- 高偏移探测的 count/complete 与最后实读段一致，总长闭环；未读缺口须可由采样证明为纯历史
- 传输回执自带的 blob_sha256/range_sha256 一致；不一致即重取该段而非拼接猜测
- 动作终态以 action_id 定向 status 回执为准，状态字段如实转述

## Counterexamples
- 回执一两个分页即可完整读完：直接线性读完即可，探测与跳步是净开销
- schema 把当前态字段放前、历史数组放最后：尾段探测只命中历史；可迁移核心是模式跳扫+定长探测，'尾部有当前态'只是启发式，方向须靠采样验证
- 任务目标就是审计该历史数组本身（统计历次 lag、找某次事件）：数组即载荷，跳过即丢答案
- 传输只支持顺序游标（next_start）不支持任意 offset 跳读：无法执行本策略，只能顺序消费
