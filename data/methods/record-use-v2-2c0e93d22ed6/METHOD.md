---
method_id: record-use-v2-2c0e93d22ed6
name: record_use证据披露与评估纪律（v2·对齐原提案与实现）
description: EVO-20260919-eabe3d37 阶段1落地（修订版）：正式评估（record_qualification/promotion 审阅）时的证据披露与判定纪律；普通 record_use 保持轻量。v1 的 record_use/qualification 混同与范围扩大已按实现核查纠正。
status: retired
source_model: glm/glm-5.3-flash
source_episode_refs: episode:863879fe-d8f5-48d9-bbdc-6ddc6eaf4b8b:90:51c6d909d857156a06a6
parent_ref: method:record-use-a7d0337b11cf
created_at: 2026-09-19T03:43:51.081375+00:00
updated_at: 2026-09-19T04:02:26.734576+00:00
---
【适用时机】对 method 做正式效果评估（record_qualification / promotion 审阅）时的取证与判定纪律；普通 record_use 保持轻量，不适用本纪律。来源：EVO-20260919-eabe3d37（accepted）。v2（2026-09-19）按原提案全文与实现核查修订 v1：v1 误把 record_use 当效果评估载体、扩大阶段2条款、窄化阶段3审计，已由实现证据逐条纠正（store.record_use 固定 task_benefit=not_evaluated，无该参数；architecture_status 的 action_trace 为最近30条滚动窗口、llm_rounds 为采集器累计计数，均不按 task/episode 隔离；evolution_complete 仅接受 executing 且限归属会话）。

一、普通 record_use 保持轻量
1. 模型按任务相关性选择 method，如实声明 applied/adapted/not_applicable/rejected；不设通用取证前置，不为记一次使用而额外查状态。
2. record_use 是适用性声明与可观测性记录：程序固定 task_benefit=not_evaluated，不承载效果判断；效果结论一律走 record_qualification。

二、正式评估（record_qualification）取证与判定
3. action_trace（最近30条滚动窗口）与 context_usage.llm_rounds（累计计数）不按 task/episode 隔离，只作解释性参考，不得直接归因"本任务"；引用时绑定 episode（qualification 归属由程序取当前 episode，模型不可自报）、方法版本（method_content_hash）与观测范围。
4. 证据不足 → verdict/task_benefit 如实标 insufficient / not_evaluated；缺失指标不得当 fail。
5. 观测与自评矛盾 → 降级 mixed/fail 并在 note 写明矛盾点；指标帮助解释、不自动代替判断：区分任务结果/方法贡献/执行成本，恢复类方法处理高难任务时异常多、耗时长本身不构成 fail。

三、范围对齐（撤销 v1 扩大）
6. "相似任务样本<3 → 不计算 delta"仅属阶段2（需 runtime 支持，未落地，供审阅）；不存在"同一 method 使用<3 不得 pass"条款。
7. delta 不自动决定 promotion（防 Goodhart 刷分）；promotion 必须人工门。

四、promotion 前审计（阶段3 原义）
8. 检索已验证 experience/episode 中与该 method 适用范围重叠的记录，列出依赖冲突与交集场景，由审阅者确认或 hold；定位为风险降低非消除，不窄化为"只核对 use_decision 一致性"。

五、完成登记与试用
9. EVO-20260919-eabe3d37 为 accepted：evolution_complete 仅接受 executing 且限归属会话；完成登记走人工 CLI（evolve-complete）。不存在"下次任何 method 使用自动测试本候选"的挂钩；试用须显式选定场景、显式 record_qualification，对比评估准确性与开销后再定流转。

残留风险：use_decision 诚实性无法程序校验，人工门兜底；本纪律只收窄影响面。
