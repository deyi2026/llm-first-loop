---
title: 项目审计基准事实_v2
scenario: A/B 记忆链路验证
root_cause: 本次审计任务（验证会话内记忆存取链路）的基准事实清单，三个具体数字分别为：测试基线 576 条、认知分层 3 级、工具输出截断阈值 3000 字符。来源：本次审计任务。首次保存因同日同 slug 冲突失败，本条以 _v2 后缀重试。
solution: 基准数字已记录
evidence: session-context
tags: [memory-link, baseline, audit, retry]
source:
  task: 记忆链路验证
  session_id: current
  source_type: memory-link-verification
status: active
created_at: "2026-08-29T01:34:51.392688+08:00"
updated_at: "2026-08-29T01:34:51.392688+08:00"
---

# 项目审计基准事实（v2）

来源：本次审计任务（A/B 记忆链路验证）

## 三个基准数字

1. **测试基线**：576 条
2. **认知分层**：3 级
3. **工具输出截断阈值**：3000 字符

## 用途

作为后续审计/回归/对照实验的锚点。

## 备注

首次保存因同日 slug 冲突未落盘，本条以 _v2 命名绕过冲突。