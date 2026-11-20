---
method_id: prevalidate-invocation-form-before-consuming-one-shot-qualification-1f1b2add4f85
name: prevalidate-invocation-form-before-consuming-one-shot-qualification
description: 消费一次性准入资格的执行调用（review_admission PASS 后的受管 push 等单次凭据动作）必须先解析执行工具的参数合同：互斥形态只传一种，且与冻结 admission target 的形态一致。依据是账本语义：畸形首调（同时传 command 与 argv）被参数层拒绝后，账本即显示 granted=1,consumed=1,state=settled，而 push 从未成功——无论精确消费时点如何，'未验证调用形态就发门控调用'与'资格损失'伴生，修正后的正确调用无资格可用，被迫新 Run 从头重审。当时在场即可用的零成本解析渠道（get_tool_schema、早前工具枚举回执、用户指令中的形态要求）应先用；用双形态对冲本身就是参数空间的扩散。
aliases: 一次性资格被空烧, 审查PASS后push被准入阻断, 先查工具schema再过闸, 畸形调用消耗凭据, 资格重签要新Run
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:37596905-cd68-421a-ad2d-d6dcf2ffd14f:114:adecf5b2fc02ed14e1bd
evidence_refs: learning:learn:614e2733870e
created_at: 2026-11-19T17:40:13.843507+08:00
updated_at: 2026-11-19T17:40:13.843507+08:00
---
## Trigger
受管动作即将消费一次性准入资格（如独立审查 PASS 后签发的单次内存凭据），而执行工具的参数合同（互斥形态如 command vs argv、必选字段）在本会话内尚未被解析确认；或用户指定的专用工具不存在、需按回执枚举的工具面重映射执行通道时。

## Discriminator
三个当时已在场的事实：(a) 早前'工具不存在'回执已完整枚举可用工具面且包含 get_tool_schema，零成本合同解析渠道可用；(b) 用户指令（只要求结构化 argv、排除 raw shell）与冻结的 admission target（git_push:<hash>:command:<hash> 单一表示）都只锚定一种规范形态；(c) 该资格是一次性凭据。任一事实都足以把'传哪种参数形态'从猜测缩成唯一答案，双形态同传与全部已知事实矛盾。

## Short path
- 闸 PASS 后、发出执行调用前，把唯一未知量显式定为'执行工具的精确调用合同'，而非直接调用
- 用零成本渠道解析合同：get_tool_schema 或先前回执中已枚举的工具说明，确认互斥形态与必选字段
- 只按冻结 admission target 对应的单一形态组一次调用（本类为仅 argv 数组，不含 command 字符串），命令与冻结材料逐字一致
- 发出前自查：互斥参数恰好出现一个、目标命令与冻结 target 一致
- 被拒即停：不在同一资格上重试，只读核验远端/本地未变，保留全部回执并如实报告原始原因，申请新 Run 重签
- push 成功后核验 remote ref==冻结 SHA，闭环停止

## Stop conditions
- 执行调用任何被拒（参数错误或准入阻断）：视为资格可能已消耗，立即停止同资格重试，只读核验状态后报告
- Host 明确 DENIED/REVISE：停止并转述原始原因
- 远端 ref 等于冻结目标 SHA：闭环完成，停止

## Verification
- 发出门控调用前自查：互斥参数恰好一个，形态与冻结 admission target 一致
- push 后以 ls-remote/只读命令核验远端 ref == 冻结 HEAD
- 如可读账本：consumed=1 应仅对应成功那一次调用

## Counterexamples
- 幂等且无门控的普通工具：多传一个参数只是免费参数错误，重发无代价，无需预检 schema 的仪式
- 资格可重复消费（会话级多次有效或直到成功有效）时，成本不对称消失，直接修正参数原样重试即可
- 工具合同已在本会话早前回执中完整可见时，再调 schema 内省是无信息冗余动作
