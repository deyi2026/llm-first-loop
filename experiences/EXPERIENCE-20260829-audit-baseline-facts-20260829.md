---
title: audit-baseline-facts-20260829
scenario: A/B 跨 turn 记忆验证
root_cause: 建立可验证的基准锚点，用于后续跨 turn 记忆一致性核对
solution: 基准数字已记录
evidence: 2026-08 项目审计
tags: [baseline, memory, audit, cross-turn]
source:
  task: memory-access-phase-1
  session: current
status: active
created_at: "2026-08-29T03:21:20.771628+08:00"
updated_at: "2026-08-29T03:21:20.771628+08:00"
---

# 项目审计基准事实（A/B 跨 turn 记忆验证）

下列三个数字为项目审计阶段确认的基准事实，作为跨 turn 记忆一致性核对锚点：

1. **测试基线：576 条** —— 测试集规模基准
2. **认知分层：3 级** —— 认知架构分层数
3. **工具输出截断阈值：3000 字符** —— 工具输出超长时截断保留阈值

来源：2026-08 审计确认；场景：A/B 跨 turn 记忆验证任务。
验证方式：后续 turn 中检索 memory/经验库时，应能稳定命中上述三条数字。