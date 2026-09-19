---
method_id: record-use-v3-1c1b05bfa2ee
name: record_use证据披露与评估纪律（v3·去强制降级）
description: EVO-20260919-eabe3d37 阶段1落地（v3）：正式评估时的证据披露与判定纪律；第5条移除源自提案原文的"强制降级"歧义，改为归属/口径/相关性三查+有效反证修正+insufficient。普通 record_use 保持轻量。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:863879fe-d8f5-48d9-bbdc-6ddc6eaf4b8b:138:78cf216493a800c1bd1a
parent_ref: method:record-use-v2-2c0e93d22ed6
created_at: 2026-09-19T04:01:54.447348+00:00
updated_at: 2026-09-19T04:01:54.447348+00:00
---
【适用时机】对 method 做正式效果评估（record_qualification / promotion 审阅）时的取证与判定纪律；普通 record_use 保持轻量，不适用本纪律。来源：EVO-20260919-eabe3d37（accepted）。

【版本链】v1 method:record-use-a7d0337b11cf（retired）→ v2 method:record-use-v2-2c0e93d22ed6（retired）→ 本版 v3（candidate）。refine/update_status 不持久化 note，替代关系以此版本链为准。
归因修正（两层，替代"六处均为候选漂移"的旧表述）：① record_use 当效果评估载体、② 指标矛盾强制降级——源自提案原文（EVO 阶段1 明文"verdict 与指标矛盾必须降级为 mixed 或 fail"），属提案自带缺陷，候选 v1 如实转录而非漂移；③ "不足3"条款扩大、④ 阶段3窄化、⑤ 虚构"自动测试"挂钩——属候选转换漂移/虚构。工具面诱因：method_manage 共用参数表含 task_benefit 而 record_use 分支不消费（store.record_use 固定 not_evaluated、无该入参），①的引入有可理解的描述混淆因素，非凭空编造。v2 已纠①③④⑤并按实现核查，但第5条保留了②的强制语义；v3 相对 v2 仅改第5条，另在第9条补登记≠验证。

一、普通 record_use 保持轻量
1. 模型按任务相关性选择 method，如实声明 applied/adapted/not_applicable/rejected；不设通用取证前置，不为记一次使用而额外查状态。
2. record_use 是适用性声明与可观测性记录：程序固定 task_benefit=not_evaluated，不承载效果判断；效果结论一律走 record_qualification。

二、正式评估（record_qualification）取证与判定
3. action_trace（最近30条滚动窗口）与 context_usage.llm_rounds（累计计数）不按 task/episode 隔离，只作解释性参考，不得直接归因"本任务"；引用时绑定 episode（qualification 归属由程序取当前 episode，模型不可自报）、方法版本（method_content_hash）与观测范围。
4. 证据不足 → verdict/task_benefit 如实标 insufficient / not_evaluated；缺失指标不得当 fail。
5. 观测与自评矛盾时先做三查：证据归属（qualification 由程序绑定当前 episode，模型不可自报）、口径（第3条的滚动窗口/累计计数语义）、相关性（区分任务结果/方法贡献/执行成本；恢复类方法处理高难任务时异常多、耗时长本身不构成反证）。有效反证成立后仅修正对应结论；无法解释时如实标 insufficient。不存在"矛盾→强制降级 mixed/fail"条款，不得把任意指标矛盾直接转为方法失败；note 写明矛盾点与三查结果。

三、范围对齐（撤销 v1 扩大）
6. "相似任务样本<3 → 不计算 delta"仅属阶段2（需 runtime 支持，未落地，供审阅）；不存在"同一 method 使用<3 不得 pass"条款。
7. delta 不自动决定 promotion（防 Goodhart 刷分）；promotion 必须人工门。

四、promotion 前审计（阶段3 原义）
8. 检索已验证 experience/episode 中与该 method 适用范围重叠的记录，列出依赖冲突与交集场景，由审阅者确认或 hold；定位为风险降低非消除，不窄化为"只核对 use_decision 一致性"。

五、完成登记与试用
9. EVO-20260919-eabe3d37 为 accepted：evolution_complete 仅接受 executing 且限归属会话；完成登记走人工 CLI（evolve-complete），登记结果为 executed/unverified——只证明方案已执行，不证明方法有效，有效性以显式 record_qualification 为准。不存在"下次任何 method 使用自动测试本候选"的挂钩；试用须显式选定场景、显式 record_qualification，对比评估准确性与开销后再定流转。

残留风险：use_decision 诚实性无法程序校验，人工门兜底；本纪律只收窄影响面。
