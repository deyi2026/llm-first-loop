---
method_id: hydrate-only-observations-not-already-in-hand-331c0db953f9
name: hydrate-only-observations-not-already-in-hand
description: 面向“下一步建议/状态核验”类请求：先列出未知量清单（运行时是否跑最新代码、修复链是否在位、演进是否登记、有无遗留目标），每个未知量只取一次权威新鲜读取；evidence ref 只是恢复句柄，仅当其对应观测内容不在当前上下文（来自早前轮次、被截断、或仅有 ref 元数据）时才 hydrate。同轮内已成功完整返回的工具调用，不再回放其证据记录。让每步由“还缺哪个未知量”驱动，而不是由“列表里还有哪些 ref”驱动。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:916:b2dda330b87d0e2d91fa
evidence_refs: learning:learn:bd757b190581
created_at: 2026-09-18T04:17:33.241488+00:00
updated_at: 2026-09-18T04:17:33.241488+00:00
---
## Trigger
用户请求下一步建议或当前状态确认，且环境中存在大量 evidence ref 与 hydration 工具；本轮内已有新鲜成功的工具调用返回完整内容，同时列表中又出现同源 ref

## Discriminator
待 hydrate 的 ref 的 source/label 与本轮内一次 [状态: success] 且完整返回的工具调用一一对应（本例：fresh service_control 已给出完整 deployment JSON，随后又 hydrate 同一 service_control ref，得到的只是同内容的 200 字符截断重放）——该 ref 不提供任何新信息

## Short path
- 列未知量清单：运行时 generation/git_head 是否最新、修复提交是否在位、演进是否登记、有无活动目标
- 每个未知量取一次新鲜权威读取（service_control / git log / goal 查询）；仅对内容未知的观测（如 evolution_complete 登记、worktree 清理回执）hydrate 其 ref
- 跳过任何与本轮已完整返回结果同源的 ref 的 hydration
- 对照新鲜运行时状态与代码 head，识别唯一 blocker 并区分操作面步骤与我方步骤
- 给出按序建议并停止；已验证的事实不再读任何来源

## Stop conditions
- 各未知量（运行时代码版本、代码链在位、演进登记、遗留目标）均有单一权威来源在握且相互一致
- 唯一 blocker 已识别且归属（操作面 vs 我方）明确

## Verification
- 最终建议中每个事实都能指向本轮一次新鲜读取或一次必要 hydration，无被重放的来源
- 抽查验证：被跳过的 hydration 若执行，其 content 应是已持有完整输出的截断子串，确认无信息增益

## Counterexamples
- 新鲜调用失败、被截断或只返回部分 payload——此时 ranged hydration 恰是获取完整内容的正确手段
- ref 来自更早轮次、其输出已不在当前上下文——必须 hydrate 才能恢复内容
- 怀疑状态已变化——应发起新鲜调用而非 hydrate 旧快照（hydration 返回历史快照而非当前真值）
- 任务本身就是审计证据账本完整性/范围哈希——hydration 是工作对象，不受此方法约束
