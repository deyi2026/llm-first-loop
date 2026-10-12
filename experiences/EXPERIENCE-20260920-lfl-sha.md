---
title: "LFL 浏览器工具三条已核事实:sha 全量语义、单分发合同、子代理观测隔离但共享物理页"
scenario: 在本 LFL 运行时规划浏览器感知/操作任务（diff 守门、投影过滤、批量动作、子代理委派）时，需要知道 content_sha256 语义、动作分发粒度与会话/物理隔离边界，避免基于错误假设设计守门规则或并发策略。
root_cause: ""
solution: sha 相等+completeness.complete=true 才可跳过重观测；provider 面无打包，单动作回执自带 after 状态；子代理可安全做浏览器只读分析但必须排除 browser_operate 且不与父浏览器序列并发（同一物理 CDP target）。
evidence: "src/llm_loop/browser/perception.py:144-207(_content_fact_basis/_content_hash_object_basis), 1559-1624(objects_canonical 与 content_sha 计算), 657-662(owner_session_sha256 校验); src/llm_loop/tools/builtin/browser_semantic_operation.py:941-960(do 单 clause/steps 注释/clauses legacy), 969-1110(批量 halt 纪律), 864-936(compact receipt 携带 after_version/diff_ref); src/llm_loop/factory.py:905-943(浏览器后端与 actuator 单例构造、固定 target_id); src/llm_loop/subagent/runner.py:985-1005(子代理独立 sid 与 owned session)"
tags: [browser_perceive, browser_operate, content_sha256, subagent_isolation, cdp_shared_target, verified_source]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-20T12:59:35.509552+08:00"
updated_at: "2026-09-20T12:59:35.509552+08:00"
---

对 browser_perceive/browser_operate/子代理源码核验（2026-09-20）得出的三条代码级事实：

1. content_sha256 覆盖全量规范化观测（scopes+scope_observations+sensor_contract+completeness+全量 objects+sensor_grounding，perception.py:1612-1624），projection_kinds/cursor/limit 只过滤返回窗口、不参与哈希。哈希前剔除 grounding_ref/observed_version，快照局部 AX ID 换内容别名，稳定 DOM 身份保留。URL 在 scope_facts 内，URL 变化必变哈希。边界：completeness 在哈希内，两次同样截断的捕获 sha 相等只证明捕获集一致——sha 相等作"页面不变"证据的前提是 completeness.complete=true。

2. browser_operate provider 合同为单动作分发：do 直达路径只编译一个 clause；steps/clauses 打包是 deliberately absent from provider schema 的历史兼容路径（browser_semantic_operation.py:941-960 注释），模型面 schema oneOf 仅 5 个单动作变体。单动作回执自动携带 after_version+diff_ref+delta 计数，动作后观测无需模型补。

3. 子代理观测层隔离为真（独立 sid：subagent/runner.py:989-993；跨会话 hydrate unauthorized：perception.py:657-662 owner_session_sha256 校验），但物理层共享：CdpReadOnlyBrowserHost 与 CdpBrowserMutationActuator 进程单例、固定 cdp_url+固定 target_id（factory.py:917-928），父子会话指向同一物理标签页。子代理工具域继承父域且不得静默缩放（runner.py:985-988）。

推论（浏览器任务操作纪律）：同页复查可用 sha+completeness 守门跳过重观测；父子不可并发浏览器序列；子代理不授 browser_operate。