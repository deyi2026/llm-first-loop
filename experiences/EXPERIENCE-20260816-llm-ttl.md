---
title: LLM 前缀缓存排查三实验法：区分精确/前缀缓存、排除 TTL、定位预算链压制
scenario: "缓存命中率低（1% 级别）或怀疑缓存不生效时，需要系统性定位根因而非猜测。本次实测：短 prompt 实验（131 token）误判\"无前缀缓存\"，长 prompt（9718 token）才验证出前缀缓存存在（追加命中 97.3%）；TTL 排除实验（同 payload 间隔 30s-300s 重发全命中）排除 TTL 因素；最终定位到 provider 级 history_budget_chars=60000 经 min 链压制全局 256000。"
root_cause: 凭先验/短实验下结论导致误判；多层预算配置（全局/provider/窗口）存在 min 压制链，只看单层配置无法发现真实压制点；热重载只重建 registry 不作用于运行中引擎。
solution: "① 缓存类型区分实验：同 payload 重发（验精确缓存）+ 前缀追加 1 条（验前缀缓存）——必须用长 prompt（>3000 token），短 prompt 有阈值效应不命中；② TTL 排除实验：同 payload 间隔 30s/60s/120s/180s/300s 重发，看 cached_tokens 是否全命中；③ 预算链定位：effective_budget = min(全局, provider级 history_budget_chars, 模型窗口×系数)——用 event_logs request.meta 的 budget 字段确认真实生效值，逐一检查三层配置；④ 修复后验证：重启进程后看 request.meta budget 变化（refresh_config 对 provider 级预算不生效，必须重启）。"
evidence: 本次会话实测：131 token 短实验零命中误判；9718 token 长实验验证前缀缓存（追加 9472/9735 命中）；TTL 300s 全命中排除；request.meta budget 从 60000→256000→800000 逐层验证生效。
tags: [缓存, LLM, 前缀缓存, 预算链, 性能排查]
source: {}
status: active
created_at: "2026-08-16T23:50:37.650820+08:00"
updated_at: "2026-08-16T23:50:37.650820+08:00"
---