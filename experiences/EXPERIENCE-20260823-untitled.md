---
title: "本地大模型防\"压缩里打转\"的参数组合与切换联动机制"
scenario: 本地模型（LM Studio/Qwen3.8-27b-mlx，窗口 131072 token）在长会话中频繁压缩：工具输出过大→history 每轮暴涨→频繁触发压缩→压缩后本地模型看不到已读内容→失忆→反复只读查询→又产生大输出→再压缩。同时本地/云端模型在同一会话切换时需保证预算与锚点正确联动。
root_cause: "本地模型\"在压缩里打转\"= 每轮新增体积大（单轮 architecture_status 即 8k 字符）撑爆远小于窗口的预算（原 history_budget_chars=12000），导致高频压缩；压缩后失忆→重复只读查询→体积再涨→再压缩。频繁压缩不是窗口不够（131072 token≈40 万字符），是预算设得远小于窗口。"
solution: "① 压缩是结果不是原因：治本是控制每轮新增体积（小查询/并行读/读完即弃/结果提炼入记忆），而非依赖压缩保底。② 参数落地（data/providers.json + .env，需重启进程生效）：local provider history_budget_chars 12000→30000（回答轮历史可见度提升、压缩频率下降；窗口 131072 token 远大于预算，安全）；COMPACT_RATIO 0.95→0.85（压缩提前在低峰平滑发生，留缓冲防撞顶被动压缩风暴；云端 1M 预算下 0.85×1M=850K 仍极少触发零回归）。③ 切换联动已由架构覆盖，无需改代码：锚点 per-provider 隔离（sess.history_anchors[provider_id]，本地压缩前移不影响云端锚点，切云端时云端锚点 0→提交全量历史=临时扩容）；预算 per-provider（_effective_history_budget 按 model_label 取 provider history_budget_chars）；缓存 per-model 切换重置（engine.py:529 cache_monitor.reset）；切换感知帧（_inject_switch_notice 提示\"切换不改变任务勿状态确认\"+search_archive 指引）。④ TOOL_ROUND_ZERO_HISTORY=0 + TOOL_ROUND_BUDGET=8000 仅对 local 工具轮生效（engine.py:478 判定），云端工具轮不受限。"
evidence: "architecture_status 轨迹：23:49 压缩后 history 41 万→1.2 万字符，两分钟内又涨回 41 万（23:51 再压）；model_catalog 实据 qwen3.8-27b-mlx context=131072；routing.py:305-329 _effective_history_budget 按 provider 取预算；session.py:92 history_anchors 按 provider 隔离；engine.py:241-296 切换感知帧。"
tags: [本地模型, 压缩, 缓存, 模型切换, 预算, providers.json, COMPACT_RATIO]
source: {}
status: archived
created_at: "2026-08-23T08:19:29.024094+08:00"
updated_at: "2026-09-06T00:15:07.572782+08:00"
---

## 2026-09-06 lifecycle review

该记录主要是旧 qwen3.8 本地运行时参数 recipe，包含 COMPACT_RATIO=0.85、30K budget 与 zero-history 联动；当前 .env 明确 COMPACT_RATIO=1.0，history budget 语义也已改为模型物理窗口/显式性能 cap，故不再作为 active 操作指南。

