---
title: glm provider 前缀缓存 TTL≈300s：命中率回退先查请求节奏，不要先怀疑结构
scenario: "多会话并行、交互间歇、服务重启频繁的时段，cache_guard 连续报 cache_hit_regression / low_hit_rate，疑似\"最近的优化破坏了前缀缓存\"；需要快速区分结构漂移 vs provider 侧行为，避免误触发排查或回滚。"
root_cause: ""
solution: 先查请求节奏与 provider TTL，再怀疑结构：① stable_prefix_fp/prefix_changed/epoch 指纹可比 → 排除结构漂移；② cache_guard 分型（ttl 型=间隔超 300s 属预期，短间隔恢复；provider 型=冷缓存/分片路由，预热即可；regression 型=绝对命中回退但前缀可比，仍归因 provider 侧）；③ evolution 落地/服务重启与命中率是相关非因果（provider 缓存按内容前缀索引，不随客户端进程变化）。命中低的首选缓解是缩短请求间隔保温，而非改动注入结构。
evidence: "web.log：16 条 cache_hit_regression 均标注\"stable_prefix/epochs/model/provider 均保持可比\"；low_hit_rate_ttl 判定\"请求间隔 649s 超 300s 缓存 TTL，属预期\"；architecture_status（2026-09-18T11:37Z）：prefix_changed=false、cache_prefix_epoch=1、last_request 命中 30.3%（11392/37541）、窗口估算 82%；event_stream：13:14–14:48 两个 browser evolution commit（3892982ac、26c649b08）。"
tags: [cache, prefix-cache, ttl, glm, cache_guard, diagnosis]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-18T19:43:44.443126+08:00"
updated_at: "2026-09-18T19:43:44.443126+08:00"
supersedes: [EXPERIENCE-20260827-glm-coding-plan-cache-hit-0, EXPERIENCE-20260821-ttl-provider, EXPERIENCE-20260816-llm-ttl]
---

现象：当日 14:00 前命中高、之后低，疑似当天优化破坏缓存。定位三步：① 查 stable_prefix_fp / prefix_changed / cache_prefix_epoch——程序侧指纹可比即排除结构漂移；② cache_guard 分型归因：low_hit_rate_ttl（请求间隔>300s，属预期，保温即可）/ low_hit_rate_provider（冷缓存/分片路由，允许预热）/ cache_hit_regression（绝对命中回退但前缀可比）。③ 时间线对照：拐点与 evolution 落地/重启窗口重叠是相关非因果——provider 缓存按内容前缀索引，与客户端进程无关。真正改变命中率的是请求节奏：单会话连续 tool loop（间隔<TTL）= 高命中；多会话并行+交互间歇>TTL+重启后冷启动 = 低命中。附带发现：排查期间实测某会话 model_aware_budget 1000000→110400、storm_breaker 触发 5 次——预算链压制才是执行力侧真风险。