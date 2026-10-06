---
method_id: derive-lookup-keys-from-observed-namespace-32cb8eb52723
name: derive-lookup-keys-from-observed-namespace
description: 写脚本按 id/key 查询本集早前输出已展示过的记录时，key 必须从已观察数据的字面格式复制（或先打印少量实际 keys 确认命名空间），不能凭记忆或自己的散文摘要重建。本集早前表格已显示 'v3h-B01' 带前缀格式，但查询脚本用了 ('strong','B01','C0') 短形式 → KeyError，花 1 次失败 + 2 次调用才恢复；按观测格式或先采样 keys 本可一次命中。自己摘要文本中被缩写的 id 不是权威命名空间。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:918cb167-56ff-4666-9f15-32f98b72c356:409:a4143cae179b0e0f99d7
evidence_refs: learning:learn:0b96028453bf
created_at: 2026-10-06T15:41:47.928193+08:00
updated_at: 2026-10-06T15:41:47.928193+08:00
---
## Trigger
需要用脚本按 id/key 查询、连接或过滤数据，且这些记录的 key 字面格式已在早前工具输出中显示过。

## Discriminator
早前输出展示的权威 key 格式（如 'v3h-B01' 带前缀）与拟用 key（凭记忆或自写摘要的 'B01'）逐字不一致——这一不一致在写脚本当时即可观察，是唯一需要核对的点。

## Short path
- 从本集早前输出中原样复制目标 id 的字面格式（含前缀/大小写/分隔符）
- 若仍不确定，先打印少量实际 keys（如 list(store)[:3]）确认命名空间，再写查询
- 用与观测一致的 key 一次完成查询
- 将查询结果与早前输出交叉核对数量与字段，一致即停止

## Stop conditions
- 查询成功且结果与早前可见输出在 case 数/字段上一致
- 数据中不存在早前显示的 id 格式——说明引用了错误来源，先回源头核实，不要枚举格式变体

## Verification
- 拟用 key 与早前输出中的 id 逐字比对（前缀、大小写、分隔符）
- 若出现 KeyError，先怀疑 key 格式而非数据缺失，立即采样实际 keys 验证
- 采样出的 keys 与查询用 keys 属同一命名空间

## Counterexamples
- key 格式从未在任何早前输出中出现（全新数据源、schema 未展示）：此时『先打印样本 keys』本身就是正确首步，不可凭猜测直接查
- 早前显示的是人类可读标签而存储用代理键（display name ≠ storage key）：需要一次显式映射查询，格式复制不适用
- id 空间跨版本重映射（迁移/重命名后旧格式失效）：必须以当前数据实际 keys 为准，而非历史输出
- 查询目标是模糊/语义检索而非精确键查找：命名空间一致性不是主要风险
