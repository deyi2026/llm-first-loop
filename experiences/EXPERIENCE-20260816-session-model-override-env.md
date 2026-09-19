---
title: 排查模型问题先查实际运行模型：session model_override 会覆盖 .env 配置
scenario: "LLM 会话实际运行在哪个 provider 可能被 session 级 model_override 覆盖（如配额耗尽降级后遗留），导致\"我以为在调 kimi，实际在调 deepseek\"——排查模型相关问题时若只看 .env 配置会被误导。"
root_cause: 会话级 model_override（switch_model 产生）持久化在 session，重启/配置修改后仍生效，覆盖全局配置；审计日志（self_correction_log）有切换原因可回溯。
solution: 排查模型/预算问题时，先查 event_logs 中 request.meta 的 model 字段（每轮真实调用模型），或查 session 文件 model_override 字段；勿假设 .env LLM_MODEL 就是实际运行模型。本会话即因此一度误定位：改 kimi 预算 256000 但实际 deepseek 预算 60000 才是压制点。
evidence: 本会话 COR-20260816 记录 kimi 配额 403 降级 deepseek；request.meta 全部显示 deepseek/deepseek-v4-flash；session 文件 model_override=deepseek/deepseek-v4-flash。
tags: [模型路由, 排查, model_override, 会话状态]
source: {}
status: active
created_at: "2026-08-16T23:50:42.178374+08:00"
updated_at: "2026-08-16T23:50:42.178374+08:00"
---