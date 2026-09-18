---
title: 缓存命中优化正确路径：纯追加+一次性固化压缩+思考链按属性省略（勿用滚动裁剪）
scenario: 需要同时优化 LLM 前缀缓存命中率与上下文 token 消耗（省 token 且不破坏缓存）时；或缓存命中率异常下降排查时
root_cause: 省 token 的滚动裁剪（tool_tail 窗口/tool_trim 分层降级/思考链按轮数裁剪）与缓存命中（前缀字节稳定）本质冲突：每次裁剪改写已提交字节 → 前缀断裂 → 命中率暴跌（13.2% 实测）；REASONING_TAIL=0 全保留思考链则输入暴涨 5 倍（20.7K→107K tokens）稀释命中率
solution: "① 前缀稳定三件套：system prompt 静态 + 头部稳定段（head_keep 早期历史字节不变）+ 尾部纯追加（TOOL_TAIL=0、TOOL_TRIM_ENABLED=false，禁止滚动降级窗口——每轮改写已提交字节直接断裂前缀缓存，实测命中率跌至 13.2%）；② 省 token 靠一次性固化压缩：调小 HISTORY_MAX_CHARS（如 400K）触发归档，中段压缩为摘要+检索指引、原文完整另存 data/archives 可 search_archive 找回（信息零丢失、压完字节不再变、不破坏前缀）；③ 思考链用 REASONING_TAIL=-1 按属性省略（仅保留携带 tool_calls 的，协议必需），比\"最近 N 轮\"窗口更优——属性固定不随轮次滚动，前缀字节稳定；④ 修改缓存相关参数前先备份 .env（cp .env .env.bak-<日期>）并经用户批准（用户约定）；⑤ 命中率观测：CACHE_HIT_SHOW_IN_ANSWER=true 在回答尾部自动回显，近多轮 99.5% 为达标基线"
evidence: EVO-20260818-72fcd94a 三段式、EVO-20260818-4e8ddc6c 滚动降级→DSH 式一次性固化压缩、2026-08-19 命中率 13.2%→99.5% 修复链（REASONING_TAIL=-1 方案A 用户批准 + HISTORY_MAX_CHARS=400000 两全方案落地）
tags: [缓存命中, 前缀缓存, 省token, 上下文压缩, REASONING_TAIL, 一次性固化压缩]
source: {}
status: archived
created_at: "2026-08-19T22:38:01.160499+08:00"
updated_at: "2026-09-06T00:15:07.572782+08:00"
---

## 2026-09-06 lifecycle review

该记录混合新旧事实：REASONING_TAIL=-1 仍是当前配置，但 HISTORY_MAX_CHARS=400K 与 CACHE_HIT_SHOW_IN_ANSWER=true 等处方已被后续架构替代；混合记录若继续 active 易把旧参数当当前方案，故整体归档，仍可 exact-ref 考古。

