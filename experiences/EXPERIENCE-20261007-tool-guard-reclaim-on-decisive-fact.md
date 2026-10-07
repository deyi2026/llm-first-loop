---
title: 回收条件的时间门在前提决策已定时即时兑现
scenario: "临时开关带生命周期注释，回收条件写成未来时点（\"2026-12-31 前无 X 立项则清理\"）；期间用户明确决策了条件的实质前提（确认不立项 X），形式时点未到。"
root_cause: ""
solution: "回收条件的时间门是\"防反悔\"的观察窗，不是必须等满的期限。决策性事实落地后条件实质已满足，即时执行清理。清理前先 grep 全引用面并区分：死配置链路（env 解析/Settings 字段/序列化/factory 装配/测试构造 kwarg）全删；有独立测试覆盖的底层能力类（如 MonotonicGuard）和被集成断言依赖的构造参数位保留——那是\"已建未接线\"能力，退役属另一决策。docs 历史快照与规则文本中的引用不改。验证三件套：残留 grep=0、受影响测试 passed、settings 解析相邻项不变。"
evidence: "evidence://v1/041c3289a2fc4d8b9123d64438378d90（.env 删除回执）；artifact://v1/ac11bb3b0f8c627011107dc64a1abedc1099d8fcaa94fc4aaa19966aa0b5bdd9（config.py 终态）；pytest 24 passed + load_settings 解析验证（tool_guard_enabled 消失、TOOL_PIPELINE/MATERIALIZE=1 保持，execute_command 回执 2026-10-07T11:40）"
tags: [config-lifecycle, dead-config, ai-rules-constraint4, closure]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-07T11:36:21.525357+08:00"
updated_at: "2026-10-07T11:36:21.525357+08:00"
---

TOOL_GUARD_ENABLED 回收（2026-10-07）实证：配置注释写"2026-12-31 前无 deny 集立项则回收"，用户确认不立项后即时执行回收。分层操作：env 入口/Settings 字段/序列化 dict/factory 装配传参/测试 kwarg 删除（evidence://v1/041c3289a2fc4d8b9123d64438378d90、artifact://v1/ac11bb3b0f8c627011107dc64a1abedc1099d8fcaa94fc4aaa19966aa0b5bdd9）；MonotonicGuard/set_guard 及 PipelineConfig.guard 构造位保留（tests 24 passed：tests/unit/test_tools_pipeline.py + test_registry_pipeline_integration.py + test_evidence_pipeline_integration.py）；docs 历史快照（RECOVERABILITY-R11/R12）与 ai_rules.md:439 规则文本不改。