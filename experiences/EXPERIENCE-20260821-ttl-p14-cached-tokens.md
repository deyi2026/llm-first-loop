---
title: TTL 探测实验方法（P14）：同前缀定时重发 + 间隔递增序列，观测 cached_tokens 归零反推窗口
scenario: 需要定论 provider 前缀缓存 TTL/窗口时，无法直接问 provider——用真实 LLM 调用实测：固定长前缀（>512 token 缓存阈值，官方要求），间隔递增定时重发，观测命中字段何时归零。
root_cause: "provider 缓存 TTL 无官方可靠公开值（或文档与实测矛盾），需本地实测；一次性同前缀两连发只能验证\"前缀建立\"，无法测窗口时长。"
solution: "脚本模式（scripts/p14_minimax_ttl_probe.py）：① 稳定前缀 ~2.5-2.8K tokens（须 > provider 最小缓存阈值，minimax 官方 512）；② 间隔序列 0/30/60/120/300/600s（递增覆盖短/中/长窗口）；③ 每次记录 prompt_tokens + prompt_cache_hit_tokens（client 已解析 provider 差异字段）；④ 命中归零即停止，反推 TTL 区间；⑤ 后台运行 + schedule 定时查询（脚本约 20 分钟）。判读注意：单点骤降不一定是 TTL（可能是负载自适应/缓存槽竞争），需多点交替数据——若\"短间隔命中、长间隔 miss、中间恢复\"则非固定 TTL 而是不稳定模式。"
evidence: scripts/p14_minimax_ttl_probe.py 实测 6 点：t0 4.9%（冷启动）→ t1/t2 97.2% → t3 120s 5.5% → t4 300s 99.4% → t5 600s 4.9%——交替波动证明非固定 TTL（负载自适应），结论写入 EVIDENCE 文档
tags: [ttl-probe, cache-mechanism, experiment-method]
source: {}
status: active
created_at: "2026-08-21T07:44:24.723682+08:00"
updated_at: "2026-08-21T07:44:24.723682+08:00"
---