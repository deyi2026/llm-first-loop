---
title: 大实施任务期间自我评估指标解读：区分任务形态重复与真实停滞、llm_call 外部错误与内部缺陷
scenario: "大里程碑实施期间（六路径 8 阶段实现 + 装配 + 集成测试 + 演示），自我评估指标出现 stagnation_rate=0.82（50 条中 execute_command 22 次）与 exception_rate=0.68（22 条全为 llm_call 错误）。需区分\"真实停滞\"与\"任务形态导致的正常重复\"。"
root_cause: "自我评估指标是纯统计（同指纹重复占比），不区分\"任务形态正常重复\"与\"真实停滞\"；异常分类未按 phase 区分 llm_call（外部网络）与 tool（内部实现）错误——导致大实施任务期间指标虚高。"
solution: "① 区分停滞类型：同指纹重复若是\"验证/确认类碎调用\"是真实停滞（应批量合并）；若是\"每阶段必做的测试/lint/冒烟\"则是任务形态的正常重复（execute_command 每阶段跑 pytest/ruff 是同命令但跨阶段不同目标，非停滞）。② exception_rate 需看 error_type 分类：llm_call 层错误（HTTP/Timeout/Network）是 API 网络问题非代码缺陷，应归因外部而非实现质量。③ 指标解读结合任务上下文：大实施任务的指标天然偏高，对比前后评估 delta 而非绝对值。"
evidence: SE-20260816-008-9ad4：stagnation 0.82（execute_command 22/50 但去重 9 指纹，跨阶段测试）；exception 0.68（22 条全 llm_call 错误，非代码缺陷）；对比 SE-004：tool_efficiency 0.85→0.95 提升（批量合并有效）
tags: [自我评估, 指标解读, 停滞率, 异常率]
source: {}
status: active
created_at: "2026-08-17T03:00:25.055938+08:00"
updated_at: "2026-08-17T03:00:25.055938+08:00"
---