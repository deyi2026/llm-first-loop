---
method_id: batch-complete-required-fields-on-parameter-rejection-71b35b88bd44
name: batch-complete-required-fields-on-parameter-rejection
description: 对状态变更类 control API（closure/acknowledge 类）首次调用前，先从工具 schema/help 或既往回执枚举必填字段全集；若已被 'requires <field>' 类错误拒绝，把错误当作部分 schema，一次补齐所有必填字段（含语义成对字段如 evidence+reason），而不是每次只补一个字段、靠连续拒绝逐个学参数。本集把 3 次闭合调用缩为 1 次。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0db9f81d-904e-4748-9ffe-692f23789e9a:2124:6f22abfffedb9acb7f57
evidence_refs: learning:learn:f147bd19457a
created_at: 2026-09-24T03:58:46.659102+00:00
updated_at: 2026-09-24T03:58:46.659102+00:00
---
## Trigger
需要在本会话中首次调用某个会改变系统状态的管理/闭环 API，其必填参数尚不完全可知；或调用刚被 'requires evidence/reason/...' 这类参数缺失型错误拒绝，正准备重试

## Discriminator
拒绝信息是显式的参数 schema 提示（点名缺失字段），而非状态冲突或权限错误——这意味着正确的下一步是补全参数而不是换动作；同时该类闭环 API 的回执/文档惯例是 evidence 与 reason 成对必填

## Short path
- 诊断阶段保持原路径：沿 provenance 读失败动作台账，找到持有 admission barrier 的具体 action_id（本集此段高效，不变更）
- 首次调用变更类 API 前，从工具 schema/help/同类回执确认必填字段全集（本例为 evidence + reason）
- 一次调用同时提供全部必填字段闭合过期单，消除 '每次拒绝学一个字段' 的串行试错
- 受理新单后按成功回执内嵌的指引异步核对终态（status, action_id=...），未查到 succeeded/failed 不宣布结果

## Stop conditions
- 变更调用返回 accepted:true / verdict:accept，且后续受理动作不再出现 barrier 冲突
- 补全字段后仍失败且错误类型不再是参数缺失（转为状态/权限冲突）→ 停止补参数，转向冲突诊断
- 用户问题所需事实已由权威回执确认，不再追加确认性查询

## Verification
- 重试一次即通过，不再出现第二个字段缺失型拒绝
- barrier 释放被间接验证：下一个受理动作成功 accepted
- 异步终态通过 status(action_id=...) 或 event_stream 核对，而非假设完成

## Counterexamples
- 工具是 strict schema、对多余字段报 unexpected keyword → 只补错误点名的字段，不得批量猜测
- 拒绝原因是状态冲突或权限不足而非缺参数 → 补字段无效，应改查状态/权限
- 只读查询类调用试错成本低 → 最小重试即可，先读文档反而绕远
