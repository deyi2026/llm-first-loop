---
method_id: bind-next-action-params-to-receipt-template-29fa06caacb9
name: bind-next-action-params-to-receipt-template
description: 多步状态变更工具流中，若上一步回执已给出下一动作的显式调用模板（如 next 字段），或本会话刚读过的 schema 已按 action 标注必填字段，应逐字段照抄绑定参数，而非凭记忆重构。本集 step1 schema 明示 target 为 restart 必填（仅 status/publish 可省略），step3 publish 回执 next 字段更直接给出 service_control(action=restart, target=..., expected_generation=283) 模板，但 restart 首发仍缺 target 被拒一次。核心修正：『读过 schema』≠『对该 action 做过必填校验』；同时模板只约束调用形状，不扩大执行范围。收益：省一次参数契约失败往返，且避免把授权外建议动作顺带执行。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f5c1ffa0-2841-47fa-898f-b45a8c54ef12:248:4796e15403635034804b
evidence_refs: learning:learn:7fc83c699a89
created_at: 2026-10-18T14:55:48.477277+08:00
updated_at: 2026-10-18T14:55:48.477277+08:00
---
## Trigger
准备发起下一个状态变更工具调用，且（a）上一步回执含显式 next/调用模板，或（b）本会话刚读取过该工具 schema 且字段描述按 action 区分必填性（如『仅某 action 可省略』）

## Discriminator
发起调用前核对：最近的回执模板字段或 schema 中该 action 的字段描述，是否已唯一确定全部应发参数（『status/publish 时可省略』即意味着其余 action 必填）；若已确定，该文本就是参数真值，不需要也不应重新构造

## Short path
- 读 schema 时推导每个 action 的必填字段映射，而非只核对当前这步要用的 action
- 执行前置事实检查（git 根/树干净/HEAD）满足 publish 前提
- publish 后从回执提取 generation 与显式 next 调用模板
- 逐字段照抄模板实例化下一调用（target、expected_generation 等），不凭记忆增删参数
- 受理后按回执声明的异步终态核对入口报告状态，并停在上次授权范围内

## Stop conditions
- 调用已受理且回执无字段级参数拒绝，参数与 schema/模板一致
- 用户目标与授权范围已达成；回执建议中超出授权的动作（如未授权服务的 restart）不执行，仅报告

## Verification
- 对照回执模板逐字段核对实际发送参数：无缺漏、无多余
- 若仍遭参数契约拒绝，以拒绝回执为权威一次性修正全部字段（回执自带修正指引），最多一次
- 确认模板建议的超范围动作未被顺带执行，scope 与用户授权一致

## Counterexamples
- 回执 next 模板列出用户未授权的目标（本集 feishu/learning 落后 4 代）：可照抄参数形状，但执行范围仍由授权决定，不能因模板出现就执行
- 高频、参数长期稳定的简单工具且已多次成功调用：每次重读 schema 校验只增加开销，无需此方法
- 服务端实际契约与缓存/预读 schema 不一致时：以服务端参数错误回执为权威修正，而非本地 schema 文本
