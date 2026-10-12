---
method_id: live-state-first-for-forward-looking-ops-questions-c18cb8033d16
name: live-state-first-for-forward-looking-ops-questions
description: 当问题是前瞻性的（下一步做什么/还剩什么/什么被阻塞），先明确决定性的未知量，并用权威的实时状态查询逐一解决（部署状态、相关代码根的 git log、目标/任务注册表）；证据日志枚举与 hydration 只用来填补仅以回执形式存在的事实，绝不作为当前状态判断的依据，也绝不重复读取实时查询已返回过的内容。本 episode 中枚举后逐条回放的历史分支，重复读取了实时状态已在手的部署信息，而最终回答里的决定性事实（运行代际落后于已提交修复、无遗留目标）全部来自实时查询。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:7f642f54-b19e-40e5-801f-c8b92661d01e:916:b2dda330b87d0e2d91fa
evidence_refs: learning:learn:bd757b190581
created_at: 2026-09-18T04:17:44.591562+00:00
updated_at: 2026-09-18T04:17:44.591562+00:00
---
## Trigger
用户在运维/部署闭环中提出前瞻性问题（下一步建议/还剩什么/什么阻塞），且当前运行时状态存在权威的实时查询面（服务状态、版本库、目标注册表）。

## Discriminator
证据索引输出本身就标注 freshness=currentness 未验证、currentness_scope=source_version_only、task_applicability=not_evaluated——这些是过去观测，无法支撑'当前状态'的主张；且任何已被实时查询返回过的内容，在重读其证据快照之前就已知是重复信息。

## Short path
- 先列出回答该问题所需的命名未知量：运行态与已提交态的差值、遗留目标/任务、仅存于回执中的未验证事实。
- 对每个未知量直接查询其权威实时源：部署/服务状态、主分支与部署根的 git log、目标注册表。
- 仅对只以记录回执形式存在的事实（如演进/登记类回执），按标签或 ID 定向 hydrate 对应证据条目，跳过宽枚举。
- 取消任何内容已被实时查询覆盖的读取计划。
- 以阻塞项优先合成建议，为每一步标注归属（操作面 vs 自己）；一旦差值与遗留集已确立即停止。

## Stop conditions
- 运行中的代际/版本头与已提交版本头均已取得并完成比对。
- 遗留目标注册表已检查，为空或已完全枚举。
- 每条建议步骤都有明确归属方，且没有任何当前状态主张仅依赖 currentness=unverified 的历史证据。

## Verification
- 将实时部署状态中的版本头与部署根的 git log 交叉核对：不一致意味着运行时陈旧而非修复缺失。
- 确认回答中没有一条'当前状态'结论仅引用 hydration 元数据而非实时查询结果。

## Counterexamples
- 任务是审计/核实上一轮实际做了什么：证据回放才是权威路径，实时状态可能已越过被审计事件。
- 实时状态查询面不可用或本身不可靠：记录证据可能是唯一来源，此时只能带着 freshness 警告使用。
- 用户明确要求总结近期活动：枚举证据日志本身即目标，不是绕路。
- 协议强制要求 hydrate 回执以完成账本合规：保留 hydration，但当前状态主张仍须由实时查询导出。
