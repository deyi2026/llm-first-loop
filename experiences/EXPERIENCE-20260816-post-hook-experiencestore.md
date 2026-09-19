---
title: 工具执行链经验前置注入：post hook + ExperienceStore 检索（已验证最短路径自动复用）
scenario: 需要在工具执行链上程序化注入经验（已验证最短路径）供 LLM 决策复用，且不破坏既有执行语义
root_cause: "工具调用前\"靠 AI 主动检索经验\"是弱约束，失败/陌生场景易重复探测；需程序化保证：执行链上自动检索并注入经验提示。"
solution: "用 post hook 实现经验注入：在 ToolExecutionPipeline 注册 make_experience_post_hook(store)——工具执行后以 (tool_name + content 前 80 字符) 为 query 调 ExperienceStore.list_active 检索 top1，语义分数≥0.25（或关键词模式）命中则把 [经验提示]（标题+id+tags，限 200 字符）追加到结果末尾，meta 记录 experience_injected；blocked 结果与异常一律 fail-open 放行。等效\"决策前带经验\"（LLM 下一轮决策时结果已含提示），复用既有 waterfall 语义与 fail-open 防御，env 开关 TOOL_EXPERIENCE_INJECT 可控。"
evidence: EVO-20260816-62977206 程序层落地（2026-08-16）：pipeline.py 新增 make_experience_post_hook，factory.py 装配（TOOL_EXPERIENCE_INJECT 默认开），6 个单测全绿 + 全量单测通过；复用既有 post hook waterfall 语义（EVO-20260814-39a10097）与 ExperienceStore.list_active 检索，零回归。
tags: [经验注入, post hook, ToolExecutionPipeline, ExperienceStore, fail-open, EVO-62977206]
source: {}
status: archived
created_at: "2026-08-16T22:41:17.643949+08:00"
updated_at: "2026-09-06T00:17:19.943416+08:00"
---

## 2026-09-06 lifecycle review

该记录依赖“工具执行后自动检索并注入 experience_tip”的旧机制。当前 `tool_cycle._inject_experience_tips` 明确为 on-demand-only compatibility observability：不得 query ExperienceStore、不得 append Message、prompt_chars=0；经验由模型显式 `search_records(kind=experience)` 发现并按 stable ref 水合。因此退出 active 普通召回，历史实现保留 exact-ref 考古。
