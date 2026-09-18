---
title: LLM 前缀缓存健康闭环：发送前门禁 + 窗口兜底（程序常态锚点管理）
scenario: LLM provider 按 prompt 前缀缓存计费；压缩锚点前移/动态注入会破坏前缀导致命中率暴跌（实测 99.7%→6.8%）。需要程序常态管理锚点：检测→拦截→恢复闭环，而不是只给 AI 事后告警。
root_cause: 锚点前移是压缩的正常副作用但破坏前缀缓存；原有投影门闸只检测构建一致性（ver+seq 匹配而输出不同），不消费命中率，对锚点变化视为正常 miss 不告警——检测与修复脱节。
solution: 独立模块 CacheHealthMonitor（core/cache_health.py）：①发送前门禁——preflight 比较稳定段指纹（system+memory+interop，per-session 基线）与上次发送，漂移立即置 force_head_keep（强制压缩保留锚点头部，当次 build 合规化）；postcheck 发送前校验，漂移审计+提示+建新基线（受控变化不重复提示），fail-open 不熔断。②窗口兜底——≥5 run 且 ≥50K tokens 命中率<50% 告警+拦截；连续 5 轮单轮命中率≥80% 自动恢复+复位窗口可再告警。③拼装规则固化进 _BASE_PROMPT 静态段（一次性，不破坏前缀）。关键教训：基线必须 per-session（不同会话注入不同，全局基线必误报）；postcheck 比较必须用同一指纹（曾用 built 前 N 条 vs stable_fp 必然不等）；恢复用单轮命中率而非窗口累计（低命中旧数据拖累）。
evidence: EVO-20260817-72fcd94a 实现 + tests/unit/test_cache_monitor.py 9 测试；实证：压缩锚点前移后命中率 6.8%（4692 次压缩事件统计）
tags: [缓存, 前缀命中, 锚点管理, 门禁, 成本优化, CacheHealthMonitor]
source: {}
status: active
created_at: "2026-08-17T20:07:17.872711+08:00"
updated_at: "2026-08-17T20:07:17.872711+08:00"
---