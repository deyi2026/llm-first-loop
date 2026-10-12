---
title: Cache-First 审计方法：LLM 请求前缀缓存命中系统排查与规范固化
scenario: "用户提出\"缓存命中应作为 agent/大模型项目开发的优先考虑项\"，需要系统性审计项目中所有影响 LLM 请求前缀缓存命中的因素（而非只查单个注入点），并把原则固化为可执行开发规范。"
root_cause: 缓存命中收益被低估：开发时容易在 system_prompt 或消息序列中插入动态内容（时间戳/计数/检索结果/协调消息），破坏服务端 KV 缓存的最长公共前缀，导致每次请求全量重算（首 token 时延+成本）。缓存命中不是性能优化而是架构原则，需检查清单约束。
solution: "1) 系统性审计 5 类前缀稳定性因素（system_prompt 静态性/tools schema 顺序/推送式注入开关/历史锚定/新注入点位置），逐一 grep 代码确认；2) 把\"缓存命中纪律（Cache-First）\"作为第五章写入 docs/development_methodology.md，含 7 条改代码前检查清单 + 验证方式（无消息轮 vs 有消息轮 system 前缀字节级一致）；3) 提交入库供团队遵守；4) 经验沉淀供跨项目复用。"
evidence: 审计确认：build_system_prompt 无动态内容；registry.schemas 顺序稳定（dict 插入序）；P1-7 injected_system 标记 + provider inject_system_notices=false 跳过推送式注入；P1-10 provider 级历史锚定；inbox 注入走 _append_or_merge 追加式合并（memory 之后，原前缀保持命中）。已写入 docs/development_methodology.md 五章 + 提交 4f76eb7。
tags: [cache, llm, prefix-stability, agent, methodology, prompt-engineering]
source:
  session: 20260816-cache-first
  agent: llm-first-loop
status: active
created_at: "2026-08-16T20:12:46.574614+08:00"
updated_at: "2026-08-16T20:12:46.574614+08:00"
---

LLM 请求前缀缓存命中审计方法（本会话实证）：① system_prompt 查时间/随机动态内容（grep time|random|count）；② tools schema 查生成顺序稳定性（registry dict 插入序）；③ 推送式注入查 injected_system 标记与 provider inject_system_notices 开关（本地模型=false 时跳过提交，llama.cpp 前缀缓存每轮命中）；④ 历史锚定查 P1-10（provider 级 anchor 持久化 + 工具轮边界对齐）；⑤ 新 system 注入查是否走 _append_or_merge 追加式合并（尾部，原前缀字节级保持）。已落 docs/development_methodology.md"五、缓存命中纪律"7 条检查清单。方法论要点：缓存命中的敌人是"前缀漂移"——任何插入/重排/动态内容都会破坏服务端 KV 缓存；修复方向永远是"静态前缀最大化 + 动态段放尾部"。