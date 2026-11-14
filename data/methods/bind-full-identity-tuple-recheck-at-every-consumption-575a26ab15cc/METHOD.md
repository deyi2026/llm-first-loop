---
method_id: bind-full-identity-tuple-recheck-at-every-consumption-575a26ab15cc
name: bind-full-identity-tuple-recheck-at-every-consumption
description: 多写入者事件账本上用 join 派生结算真值、或维护跨调用 pending 预留/一次性授权门禁时，交付前把『代码实际绑定的身份维度集合』与『schema 提供的身份维度集合』做差集：账本已带 call_id/attempt_id/origin_run_generation 而代码只绑子集（只记 settled id、不筛本 run、授权时查一次消费时不复查、digest 用本地 raw 形状），每个未绑维度都是交叉审查会点名的 fail-open。修法：join 前按权威契约把维度筛齐；跨模块 digest 按对端 canonical 形状规范化；引用外部可变状态的绑定在每次消费点复查；pending 预留按 owner 身份独占。每个曾未绑维度配一个负测。
aliases: 事件账本防串账自检, join 前先筛本 run 再对 call_id, 授权一次不够要每次复查, 绑定维度差集审计, 异 run 事件防污染, 反例打回前自审
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:59d664ee-98e2-4f7f-bf0b-79cdb910e980:1838:44bec4c15fb0c8d3fb37
evidence_refs: learning:learn:d9e7d649f1f8
created_at: 2026-11-14T01:17:21.065293+08:00
updated_at: 2026-11-14T01:17:21.065293+08:00
---
## Trigger
实现或修改从共享事件账本（多 run、多 attempt、多 call 并存）join 派生真值的结算路径，或存在 pending 预留/一次性授权门禁，即将交付接受对抗性交叉审查时

## Discriminator
事件模型与真实账本样本已携带完整身份维度（call_id、attempt_id、origin_run_generation、事件种类），且模块自身契约/docstring 已声明权威 join 语义（如 opened+settled 双事件 join）；若实现绑定的只是这些维度的真子集，未绑维度恰好就是异 run/重试/并发能穿过的位置——这是交付当时就已可见、无需事后答案的事实

## Short path
- 列出每类被消费记录在 schema 中的全部身份维度，以及权威契约声明的 join 范围
- 对每个 join/过滤/预留标注代码实际钉住的维度，diff 出 schema 有而代码未绑的维度，先修差集
- 跨模块 digest/签名改为按权威方 canonical 形状规范化后再比对，不传本地 raw 形状
- 引用外部可变状态（目标文件、scope、SHA）的门禁，把绑定校验移到每次消费点重跑，而非仅授权时一次
- 每个曾未绑维度写成负测（异 run 完整事件污染、第二次物理 attempt、篡改 digest、target 漂移/逃逸）后再交付，冻结基线用树哈希证明未动

## Stop conditions
- 每条被消费记录在 schema 提供的全部相关维度上被唯一绑定；任一维度缺失/重复/异源污染均 fail-closed（UNKNOWN+stop）而非误结算
- 每个门禁在每次消费点复查绑定事实；pending 预留按 owner 独占，消费后才能重新武装
- 维度差集为空，且每个曾未绑维度有对应负测通过、连续多次 attempt 回归无误停

## Verification
- 注入异 run/异 call/重复事件样本，确认结算路径第一次即 fail-closed 而非误结算
- 连续 2~4 次物理 attempt 回归：每轮正确结算、无误停、allocations 与实测一致
- 对拍权威模块的 canonical digest 形状；冻结基线前后 write-tree 哈希一致

## Counterexamples
- 单写入者、单 run 的嵌入式日志：generation/attempt 维度不存在或无意义，强行全维绑定反而破坏合法重放，应按 schema 实际存在的维度绑定
- 一次性只读批量分析：无 pending 预留、无多次消费点，『每次复查』是空操作，属过度设计
- 契约显式声明记录跨 attempt 共享（如审计流水）：未绑 attempt 维度是文档化特性而非缺陷
