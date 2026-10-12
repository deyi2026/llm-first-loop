---
method_id: record-use-a7d0337b11cf
name: record_use指标强制披露与人工门
description: EVO-20260919-eabe3d37 阶段1落地：method 记录/晋级前的强制披露纪律与人工门程序（零架构改动）
status: retired
source_model: glm/glm-5.3-flash
source_episode_refs: episode:863879fe-d8f5-48d9-bbdc-6ddc6eaf4b8b:18:2fb05fb7e9c902d0ad3d
evidence_refs: EVO-20260919-eabe3d37
created_at: 2026-09-19T02:33:25.736367+00:00
updated_at: 2026-09-19T04:02:26.727442+00:00
---
【适用时机】任何 method_manage record_use / promotion 评估前。来源：EVO-20260919-eabe3d37（已批准，accepted）。

一、record_use 前置取证（强制）
1. 调用 record_use 前，必须先只读取证：architecture_status（action_trace / context_usage）与 task_frontier 的 task 终态，取回本任务机械指标：loop 轮次、重试次数、exception 数、耗时、终态。
2. 上述只读回执必须列入 record_use 的 evidence_refs；无 evidence_refs 的 task_benefit=pass 一律不采信。

二、判定规则
3. 机械指标与自评矛盾 → task_benefit 降级（pass→mixed/fail），以指标为准。
4. 同一 method 的可采信使用样本 <3 → 评估输出 insufficient，不得给 pass。
5. 指标 delta（相对旧方法）不自动决定 promotion——防刷分；promotion 必须过人工门。

三、promotion 前审计（替代严格回放）
6. 不做严格 trace 回放（trace 非脚本、环境已变，确认不可行）。改为重叠场景审计：从 episode/已解决片段中抽取与该 method 声称适用范围重叠的场景，抽样核对历次 use_decision 与实际结果的一致性。

四、激活后监测
7. method 激活后，跟踪其各次 record_use 指标趋势；趋势恶化 → 触发 refine/hold。

五、已知残留风险
8. use_decision 的诚实性无法完全由程序校验，人工门是兜底；本方法不消除该风险，只收窄其影响面。
