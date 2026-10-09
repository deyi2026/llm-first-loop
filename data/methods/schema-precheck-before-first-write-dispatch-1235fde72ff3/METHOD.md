---
method_id: schema-precheck-before-first-write-dispatch-1235fde72ff3
name: schema-precheck-before-first-write-dispatch
description: 多动作控制面工具常对不同 action 使用不同参数名（本例 restart 用 target，update 才用 restart_target）。本会话首次派发写类 action 时若凭猜测构参，会把一次确定性契约读取变成『失败探错→读 schema→重发』三跳，并留下一次失败的变更类调用。当任务指令已给出 defer-to-schema 信号（如『以实际工具 schema 为准』）或参数名歧义（service/target 二选一）时，schema 就是派发前的契约：先读一次、按契约一次性构齐全部字段。失败后纠错仍按回执要求一次性修正全部字段。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8596f046-ed0c-41a4-bf52-8a43baa1c2c5:10:e7b74946157537565a92
evidence_refs: learning:learn:15077025a384
created_at: 2026-10-09T09:18:04.515511+08:00
updated_at: 2026-10-09T09:18:04.515511+08:00
---
## Trigger
本会话首次调用多动作控制面工具的写/派发类 action（restart/publish/update 等），且该工具参数 schema 本会话尚未读取；同时指令或上下文已出现参数命名歧义信号（如 service/target 二选一）或『以实际工具 schema 为准』类 defer 语句。

## Discriminator
首次派发前已可见：指令自身对参数名不确定并指定实际 schema 为唯一权威。这条当时已知事实足以把『猜参数名→被契约拒绝→读 schema→重发』缩成『先读一次 schema→按契约一次性构参』，不依赖任何事后信息。

## Short path
- 识别本次 action 为写/派发类，且目标工具 schema 未在本会话读过
- 检查指令/上下文中是否有命名歧义或 defer-to-schema 信号（命中 discriminator）
- 调用 get_tool_schema 读完整契约，确认字段名、enum 与字段对 action 的归属（如 target vs restart_target）
- 严格按 schema 一次性构齐全部必填字段（含 expected_generation 等 CAS 保护字段）后派发
- 以回执 status=accepted 且无参数错误为通过；accepted≠succeeded，按任务约束报告后结束本轮

## Stop conditions
- schema 已确认契约且派发回执无参数错误（accepted）
- 本会话已有同工具同 action 的成功调用或已读过 schema，则跳过预读直接构参
- 只读、低成本 action（如 status）失败代价可忽略，不强制预读

## Verification
- 回执无参数契约错误，全部字段一次通过
- 派发参数与授权范围一致：target 仅授权目标，expected_generation 等于已核对过的 desired generation
- 状态报告沿用回执原文语义（受理 accepted，不宣布终态 succeeded）

## Counterexamples
- 本会话此前已成功调用同 action 或已读过 schema——再读属冗余动作，直接复用已知契约
- 纯只读、幂等且便宜的调用（如 status）：猜错重试即可，强制预读反而增加固定开销
- 参数名无歧义且已被上游回执/文档显式给出时，直接按给定构参，无需 schema 预读
- schema 获取不可用或代价高于安全试错成本、且该 action 无副作用风险时，允许失败驱动纠正
