---
title: A/B 实测确认：HashEmbedder 是词法不是语义，换真语义模型排名改善 ~2.5× 但仍需重排
scenario: "llm-first-loop 的 EMBEDDING_PROVIDER=hash（字符 n-gram 哈希向量）检索质量差，需验证瓶颈是\"语义嵌入\"还是\"检索系统\"。用真实语料（21,673 条 memory+archive 文档）+ 7 条人工构造查询（1 条词面重叠 + 6 条同义改写零词面重叠）做 A/B：HashEmbedder(dim=128) vs BAAI/bge-small-zh-v1.5（本地已缓存，批量编码）。"
root_cause: ""
solution: "结果：hash 语义查询平均排名 ~4,826/21,673，bge ~1,936（好 ~2.5×）；Top-20 命中 bge 3/7 vs hash 1/7；词面重叠查询两者都 #1-#4。结论：①\"缺的是语义\"方向正确——hash 本质是词法匹配，换真语义模型显著改善；②但\"不是系统\"过强——即使真语义，Top-5 也只有 1/7，单向量稠密检索在噪声语料（原始会话行、无重排）上不达标，还缺 chunking/hybrid/cross-encoder 重排。检索系统（RRF 三通道融合）架构已完整，缺的是：真语义嵌入 + 重排层 + 语料粒度治理。"
evidence: "/tmp/ab_test_v3.log（全量 21,673 条语料对照结果）；/tmp/ab_test_v2.log（3,000 条子集对照）；scripts/ab_test_embedding.py（实验脚本）；src/llm_loop/memory/embedder.py L38-68（HashEmbedder 实现，确认为字符 n-gram 哈希非语义）"
tags: [embedding, retrieval, ab-test, hash-vs-semantic, bge-small-zh, eval-methodology]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-16T12:31:36.790944+08:00"
updated_at: "2026-09-16T12:31:36.790944+08:00"
---

实验设计关键点（复用价值）：① gold 必须先验证存在于实际语料（grep/子串检查）再跑 A/B，否则两边全 miss 无区分度；② 语义模型必须批量编码（一次前向编全语料），逐条编码会慢 30 倍以上；③ 测试集要分 literal（含关键词）与 semantic（同义改写、零词面重叠）两组，才能隔离"语义"变量；④ 语料采样截断（max_docs）会产生伪 dropout——被剔除的 gold 要区分"我的截断排除"还是"生产索引真的没有"；⑤ 长文档截断（800 字）也会导致 gold 落在截断之外而误判 miss。