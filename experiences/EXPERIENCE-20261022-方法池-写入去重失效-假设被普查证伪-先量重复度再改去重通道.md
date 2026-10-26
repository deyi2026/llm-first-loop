---
title: 方法池“写入去重失效”假设被普查证伪：先量重复度再改去重通道
scenario: 方法卡池 1362 张（candidate 1307），反思阶段“已有方法简报”按状态配额挑 30 条、不看本轮 episode。直觉判断：去重窗口太窄→池子灌水→近重复卡拖累检索。据此准备把简报选择改成相关性排序。
root_cause: 把“池子大”当成“池子脏”。池子增长本身不等于重复堆积；而“状态配额 + 时间倒序”看起来盲目，实际旁边还有一条同源相关性通道在兜底。缺的是重复度与通道覆盖的实测，不是新机制。
solution: 改代码前先做全池近重复普查：对 1361 张卡的 description 做 bigram Jaccard（倒排索引枚举候选对），结果 ≥0.3 的卡对只有 3 对（最高 0.67），近重复≈0。再核 reflection payload 结构：已有 related_methods 通道（_discover_related_methods → 同源 query，limit=6），去重上下文本来就是相关性驱动的。结论：去重不是瓶颈，改动只有预防性收益、无实测失败可修，按“无证据不引入复杂度”回退（保留 30 条状态兜底通道）。同轮改为攻真实瓶颈——检索排序：idf 加权 + description 命中佐证规则，冻结 goldset 上关键词 hit@1 .333→.600，生产融合 hit@1 .567→.633。
evidence: 池普查：data/methods 1361 张卡 description bigram Jaccard ≥0.3 仅 3 对（0.67/0.56/0.32），两次独立实现（我与子代理）结果一致。通道覆盖：goldset 30 query，related_methods(limit=6) hit 21/30，30 条简报通道 25/30，仅 6/30 为主通道 miss 后接住。检索改动实测：/tmp/method-baseline-pre-20261022-2325.json 与 /tmp/method-after-idf-corroborate.json（prod hit@1 .5667→.6333，hit@5 .9→.9333）。落地：commit 868c90eec（分支 feat/method-retrieval-idf，本地未 push）。
tags: [方法系统, 去重, 评测先行, 证伪, 检索排序]
source:
  kind: session
  ref: method-system-supervision-20261022
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-22T23:42:17.035461+08:00"
updated_at: "2026-10-22T23:42:17.035461+08:00"
---