---
title: LLM 前缀缓存 0 命中根因：动态注入并入 system 主体导致前缀每轮漂移
scenario: DeepSeek 前缀缓存实测 0 命中（重启后从 8% 跌到 0%）。排查发现主请求 system 消息每轮变化（动态段并入 system content：memory 检索结果/压缩 extras 归档目录 386→389 条等，约 1720 字符/轮），DeepSeek 按消息前缀字节匹配 → system 整体不命中 → 全 miss。
root_cause: "前缀缓存按字节一致匹配；动态内容并入 system 主体 = system 每轮变化 = 整条 system 不命中 = 全 miss。此前\"system 静态/追加\"约束只防了中间插入，没防动态段并入 system content 的累积漂移。"
solution: 把动态注入（memory/压缩 extras）标记 _dynamic 并转独立 user 消息，system 主体字节稳定 → 前缀命中恢复（实测 0% → 22%，system 三次字节一致）。配套：API 非流式路径补传 tokens_cache_hit（曾恒显 0 假象）。验证用 system 指纹对比（两次 run 的 sys hash + len 差异定位漂移段）。
evidence: 2026-08-17 实测：sys hash 12c62bc950ae(len 8610) vs d68a8859d7ed(len 8665) 每轮变；修复 b0c7bf7 后 system 三次字节一致 04a269173aa4，命中 0%→22%；大预算后 96-99.9%
tags: [cache, prefix-cache, system-prompt, deepseek, dynamic-injection]
source: {}
status: archived
record_kind: experience
verification_state: legacy_unclassified
created_at: "2026-08-17T22:57:52.727574+08:00"
updated_at: "2026-09-11T19:33:32.133104+08:00"
superseded_by: "runtime:prompt-authority-p1c"
last_verified_at: "2026-09-11T19:33:32.133104+08:00"
---

## 完整排查链
1. 现象：重启后缓存 0 命中（此前 8%）
2. 指纹证据：两次 run sys hash 不同（len 8610 vs 8665）——system 每轮变
3. 定位漂移源：memory 检索注入 + 压缩 extras 归档目录计数（386→389）每轮并入 system content
4. 修复：_dynamic 标记 → 转独立 user 消息（不并入 system 主体）
5. 验证：system 指纹三次一致 + 命中率恢复

## 关键原则
- system 主体必须字节级稳定（前缀缓存锚）——任何动态内容不得并入
- 动态内容（memory/快照/inbox/extras）一律独立消息或尾部追加
- 用 request.usage 事件（含 cache_hit/cache_miss）逐轮审计，勿信 API 面板（曾因漏传恒显 0）

## 反例（避免）
- 把 memory 检索结果并进 system content（前缀破坏）
- 非流式路径不传 tokens_cache_hit（可观测性盲区）