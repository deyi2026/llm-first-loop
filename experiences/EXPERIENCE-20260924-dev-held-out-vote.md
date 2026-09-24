---
title: 融合权重消融阴性结果：dev 增益未过 held-out + vote 共识重排反噬
scenario: retrieval 多查询 RRF 融合的权重调参（llm-first-loop evals/retrieval_ab，2026-09-24）：goldset 25 条兼作 dev set，需要验证 orig 加权/一致性重排是否优于等权 RRF
root_cause: "多查询融合权重消融中，dev（goldset 25，兼作开发集）上 ow2vote h@5 +1 像是改进；held-out（8 条 N-queries）方向性验证 Δ=0 未复现。教训有二：(1) 在兼作 dev 的 goldset 上继续调参会产生过拟合诱惑，held-out 拦截了它——预声明决策规则（h@5,h@1,MRR 字典序）比事后看数更诚实；(2) 共识投票重排（score×出现列表数）在变体质量低于 orig 时系统性反噬：奖励跨列表共识的干扰项、惩罚只在 orig 命中的 gold（dev 上 5 条 rank1→2 的一致模式）。"
solution: 等权 list-RRF(k=60) 保留为当前最优（h@1 9/h@5 16/MRR 0.505）；vote/ow2vote 方向否决；纯 ow2 的 held-out 改善（n=8，2 条）仅记为后续假设不采纳。消融脚本固化共享检索收集+预声明决策规则模式（run_fusion_weight_ablation.py）。
evidence: evals/retrieval_ab/fusion-weight-ablation-20260924-175813.json（equal 复现 9/16/0.505；ow2vote dev h@5 17 但 h@1 9→6、5 条 rank1→2；held-out Δ=0/0/+0.006）；docs/REPORT-20260924-fusion-weight-ablation.md；commit abaccb852
tags: [retrieval, fusion, held-out-validation, negative-result, evaluation-methodology]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-24T18:12:37.237176+08:00"
updated_at: "2026-09-24T18:12:37.237176+08:00"
---

机制：变体列表质量参差时，共识乘法（score×出现列表数）系统性奖励"orig+变体同时出现的干扰项"、惩罚"只在 orig rank1 命中的 gold"——变体的系统性偏差被 vote 放大。应用约束：融合评测若在同一 goldset 上迭代调参，任何 +1 都应先过 held-out；预声明决策规则+held-out 是拦截叙事漂移的低成本手段。