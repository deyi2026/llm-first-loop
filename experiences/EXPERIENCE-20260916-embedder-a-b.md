---
title: "隔离验证\"缺的是语义不是系统\"：同一检索系统只换 embedder 的 A/B 方法"
scenario: "检索系统嵌入质量存疑时，如何隔离\"系统问题\"vs\"嵌入语义能力问题\"并量化差值"
root_cause: ""
solution: 设计三类标注集（语义改写/词法对照/噪声）+ 两口径测试（纯语义通道 vs 端到端 RRF），同一检索系统只换 embedder 实例做单变量 A/B，向量缓存预填内存隔离生产，人工核验失败案例区分标注问题与真检索失败
evidence: evals/embedding_stage2/ab_results.json + ab_e2e_results.json + README.md；commit 73c4d947
tags: [embedding, retrieval-quality, ab-test, isolation-method]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-16T14:01:20.573972+08:00"
updated_at: "2026-09-16T14:01:20.573972+08:00"
---

问题：生产嵌入是字符 n-gram hash（EMBEDDING_PROVIDER=hash），需证明"系统其余部分没问题，只缺真语义嵌入"，否则换 provider 是盲动。\n\n方法（可复用）：\n1. 三类查询标注集：A=语义改写（词面不重叠，实测 hash_cos(q,target) mean 0.30 作量化前提）；B=词法对照（专名精确词）；C=噪声（语料无对应）。\n2. 两口径隔离测试：纯语义通道（只余弦排名）+ 端到端 RRF（复刻真实链路：MemoryStore.search(query.split()) 关键词 seed + SemanticRetriever RRF）。\n3. 单变量：两臂同一 SemanticRetriever 代码，只换 embedder 实例；候选向量缓存预填内存（不落盘不污染生产缓存）。\n4. 近重复防护：3-gram Jaccard>0.6 条目记为 alternates，命中任一算对。\n5. 失败案例人工核验 top1 内容，区分"标注单一性"与"真检索失败"。\n\n结果（1488 条真实记忆语料，40 查询）：\n- A 类端到端 Recall@5：hash 0% → bge 45%（纯语义 0%→50%）；A 类关键词通道 seed 命中 0/20，语义通道是改写查询唯一召回来源\n- B 类端到端两者 100%（关键词通道兜底，词面可匹配场景现状不缺）\n- C 类噪声：hash@0.22 阈值 100% 假阳性返回 → bge@0.50 拦掉 50% 且 5 条正确降级 keyword\n- bge 失败 10 条人工核验：多为"主题相关不对题"竞争条目挤出 target，是真排序问题\n\n结论：判断成立（差值即语义贡献，系统代码零改动），但 bge 非银弹——同域密集语料上限 ~50%，剩余需 query 改写/混合排序/更强模型。