---
title: 缓存命中率排查方法论：区分字段口径/TTL假设/预算差异/使用模式四层，避免把 provider 特性误判为配置错
scenario: "用户报告\"换 minimax 缓存命中一直比较低\"，问是不是上下文窗口大小/统一预算问题。排查链条：① 字段解析差异（client.py 三 provider 走不同路径：DeepSeek 扁平 prompt_cache_hit_tokens、MiniMax 嵌套 prompt_tokens_details.cached_tokens——部分场景不返回导致显示 0）；② TTL 假设（官方文档\"5min\"被本地日志 24s 仍 miss 反驳）；③ 预算差异（200K vs 1M 曾被我误列为主因）；④ 用户纠正\"改方案前 200K 一直命中且省 token\"→ 真相是使用模式：minimax 被闲置（默认模型是 deepseek）→ 前缀冷却 + 冷启动重建，活跃时 97-99% 机制正常。"
root_cause: "单一现象（命中率低）有多个可能根因叠加（字段缺失显示 0 + 闲置冷却 + 负载自适应不稳定），逐层排查时若只停在某一层（如\"预算小\"）会误判；且外部文档数值未经本地实证就引用，导致\"TTL=5min\"假结论。"
solution: "排查 provider 缓存命中率按四层逐层排除：① 字段口径（先确认 client 是否真实解析到该 provider 的缓存字段，缺失=显示 0 而非真 miss）；② TTL/机制假设（用 P14 式定时同前缀重发实测，勿直接采信外部文档——\"5min\"与本地 120s 骤降、300s 恢复矛盾）；③ 配置差异（per-provider history_budget 是设计非错误）；④ 使用模式（闲置冷却 vs 活跃——活跃时 97%+ 说明机制正常）。教训：外部文档值（TTL=5min）必须标注\"待验证假设\"不写入权威文档；用户的历史实证（曾 200K 一直命中）是修正归因的最强信号，比代码推断更可信。"
evidence: "client.py:343-351 三 provider 字段路径；P14 实测 t0-t5（30s/300s 97-99% ↔ 120s/600s 5%，非固定 TTL）；docs/local/EVIDENCE-minimax-cache-mechanism.md（24s miss 反驳 5min）；.env.bak-20260819 注释\"切回 deepseek（M3 测试充分，命中 99% 省钱）\"证明 minimax 活跃时曾高命中；用户实证\"改方案前 200K 一直命中\""
tags: [cache-hit, minimax, ttl-probe, diagnosis-methodology]
source: {}
status: active
created_at: "2026-08-21T07:44:24.723077+08:00"
updated_at: "2026-08-21T07:44:24.723077+08:00"
---