---
method_id: receipt-driven-one-shot-contract-fix-with-adjudication-reason-af96d2f84bf5
name: receipt-driven-one-shot-contract-fix-with-adjudication-reason
description: 在参数契约强制的控制面/工具上，结构化失败回执本身就是修正契约：它点名缺失字段并附条件升级条款（如'按本回执一次性修正全部字段；若需字段类型/enum 再读 schema'）。当命名字段自描述（reason/evidence 等自由文本）且无其他违约项时，直接一次性补全重发，不先读全量 schema；仅 enum/结构/跨字段歧义才升级。更进一步：pending 提示点名裁决类出口（verify_acknowledge/override 等）并附带依据（如 superseded=true）时，裁决=对证据下结论，首调就应把该依据作为 reason 携带，可整轮消除失败往返。本集：漏 reason 被拒后又读了一次全量 schema，而回执本已自足；且依据在首调前就已存在于 hint 中。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d866acd6-9a96-482a-bc4b-5addb1b75762:1:f146f5452c3994f27da5
evidence_refs: learning:learn:f5d16110b588
created_at: 2026-10-13T21:42:02.239250+08:00
updated_at: 2026-10-13T21:42:02.239250+08:00
---
## Trigger
工具/控制面调用因参数契约不满足被结构化回执拒绝，回执点名 missing/invalid 字段并自带修正指引（如'按本回执一次性修正；若需类型/enum 先读 get_tool_schema'）；或 pending/状态提示已点名某裁决类动作（verify_acknowledge/override/release/adopt）并给出裁决依据（如 superseded=true）。

## Discriminator
回执是否自足：命名字段为自描述自由文本（reason/evidence/note）且回执未列其他违约项→可直接补全；字段为 enum/结构体/跨字段约束→才需 schema。首调前判别：裁决类出口是对核验证据下结论，若 hint 已给依据且现值已核实（如新代进程健康运行），则 reason 的内容在调用前就已存在，无需等失败回执提醒。

## Short path
- 读只读状态得 pending hint：确认待收口项、动作名与已给依据（未知量：要裁决什么、依据是什么）
- 核对依据现值（目标进程/代次当前健康）后，首调裁决动作即携带 reason=依据+核验事实，消除失败往返
- 若仍被契约回执拒绝：解析回执点名字段与条件升级条款，自描述字段直接按回执一次性补全重发，不读全量 schema
- 仅当字段是 enum/结构/跨字段歧义时 get_tool_schema 一次，随后一次性修正
- 以同 action_id 的成功回执（accepted=true）收口并继续任务，不再对同一事实做额外复查

## Stop conditions
- 目标动作的成功回执已返回且 action_id 与待收口项一致
- 一次性修正后重发即成功，无第二次契约失败

## Verification
- 成功回执 accepted=true 且引用同一 action_id
- 重发调用补全了回执点名的全部字段，未引入新违约项
- 首调携带的 reason 能独立复述裁决依据（新代接管+现进程健康）

## Counterexamples
- 缺失字段是 enum 或带格式约束且回执未给取值（如 verdict 枚举）——必须先读 schema，盲自描述猜测会造成第二次失败
- 失败是 transient（超时/5xx）而非契约违约——应重试而非改参数
- 回执含糊或列出多项相互依赖的违约项——先读一次 schema 再统一修正更省
- 简单只读工具的偶发笔误——直接重发即可，不套裁决/契约框架
