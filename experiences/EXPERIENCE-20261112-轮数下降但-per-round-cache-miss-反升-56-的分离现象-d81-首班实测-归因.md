---
title: 轮数下降但 per-round cache miss 反升 56% 的分离现象（d81 首班实测，归因未定）
scenario: 首班 d81 晚班：总轮数 154（vs d80 ~200，下降）但真实未命中 tokens 2.003M（vs d80 1.67M，上升 20%）；每轮平均 miss 13.0K vs 8.3K（+56%）。轮数提效与 token 成本出现分离。
root_cause: 归因未定（三个候选：a 本班上下文更长/总分段更多；b 前缀稳定性劣化致 cache 失效——D7 compaction gate 尚为 observe-only（shadow_not_delivered），未触发拦截；c 与 d80 基线口径差异未对表）。观察事实本身已验证。
solution: 提效验收必须同时挂轮数与 per-round miss 两个维度（M5 不只看总量）；归因行动序：与基线逐项对表→调 compaction/gate shadow 数据→前缀稳定性归因成立则评估 D7 gate 从 observe-only 升级。连续 3 班数据后再定红线调整。
evidence: docs/ASSESS-20261112-promo-shift-m1m5-firstshift.md §4（M5 实测与每轮均值计算）；d80 基线见设计文档 §1（74.73M in/73.06M hit/1.67M miss）
tags: [cache成本, token经济学, 提效验收, 推广班]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-12T23:30:25.993790+08:00"
updated_at: "2026-11-12T23:30:25.993790+08:00"
---

轮数与 per-round miss 是两个独立维度：提效设计不能只降轮数。cache miss 上升 56% 说明前缀稳定性或上下文结构劣化——在 provider 按全量重复计费的现实下，总成本可能不降反升。归因行动序：①基线对表排除口径差异；②查 compaction/gate 行为；③若前缀稳定性问题则评估 gate 升级。