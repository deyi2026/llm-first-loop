---
title: 工具密集会话缓存命中率波动属正常现象（非故障），纯对话才见快速恢复高位
scenario: 诊断缓存命中率（cache_health/cache_guard 的 recent_hit_rate）时，在工具密集会话中命中率于 49%-99% 间持续波动，且 win_hit 停在固定旧前缀（如 8320/8704）而 win_in 随轮次增长（9K-21K 跳变），容易被误判为缓存故障/恢复失败/模型切换异常。
root_cause: "缓存按前缀命中：每轮工具调用都在历史末尾追加新字节，新增部分全 miss，故出现 win_in 增长而 win_hit 不变（命中的是同段旧前缀）；命中率高低取决于任务工具密集度与轮次跨度，与缓存是否正常工作无直接关系。早前\"切换后 3-4 轮恢复 98%\"的推演只在纯对话/轻工具会话成立。"
solution: "判定要点：① 命中率形态取决于任务工具密集度——工具轮每轮向历史追加新字节（工具名+参数+结果），前缀持续变化导致命中率天然波动，属正常；② 纯对话/轻工具轮才见快速恢复高位（92.8%-98%+）；③ 模型切换是叠加因素（切换瞬间低），在工具密集下波动会掩盖恢复曲线，不应据此判定缓存未预热；④ 观测数据源应优先用 event_logs 的 request.usage 逐轮回溯（每轮自动记录、可回溯、不依赖 AI 在线），而非 schedule 定时自检（会话结束后提醒无人执行，数据易断档）；⑤ 判定\"是否故障\"看 hit 是否随 in 同步增长，而非瞬时 rate 高低。"
evidence: "镜像 56 轮真实曲线：minimax 稳定 85-89% → 切 deepseek 91.1% → 工具密集期序列 56.6/48.8/99.5/66/67/49/60/80/92.8/62.8/53.6% 持续波动；纯对话轮才见 92.8% 高位；证据为 hit 停在固定 8320/8704 而 in 在 9K-21K 间跳。另 LFL 基线观测（2026-08-20T08:31:02Z, rate=0.6805）与镜像数据同源形态。"
tags: [缓存, cache_health, 命中率, 诊断, 工具密集, 观测方法, event_logs]
source:
  kind: current_runtime_reverification
  contract: src/llm_loop/event_log/model.py request.usage cache_hit_rate=cache_read_tokens/tokens_in
  audit: "2026-09-06 current-format event_logs: 804 same-contract transitions; 98 ratio drops >5pt with nondecreasing cache_read_tokens"
status: archived
created_at: "2026-08-20T16:35:34.506485+08:00"
updated_at: "2026-09-06T00:18:15.076906+08:00"
promoted_to_rule: RULE-AI-16
last_verified_at: "2026-09-06T00:16:22.443906+08:00"
---

## 2026-09-06 lifecycle review

核心方法论仍适用：判断 prefix cache 是否退化应同时看绝对 cache_read_tokens 与 tokens_in，而不能只看比率。当前镜像 current-format request.usage 复核得到 804 个同 runtime/model/stable-prefix/epoch 相邻 transition，其中 98 个 hit rate 下降超过 5pt 但 cache_read_tokens 不减，符合“新增尾部扩大分母”的正常形态。历史具体数值仅作背景。
