---
title: 压稿子体积时删「正文未逐字引用的英文原句摘录」会被窄复审判 P1
scenario: 为压进宿主准入体积上限，把参考来源「摘要原文含」里正文没有逐字引用的 15 条英文片段删掉（正文有中文转述，完整原文仍在 candidates_dump 并加了指针）。窄复审子代理判 FAIL：P0=0 P1=1——正文断言「跨 3 个 backbone、其中一个上 7 个任务套件」在稿内参考来源找不到英文出处；同时把 15 条列为「稿内锚点缺失」。
root_cause: ""
solution: 稿内「原文出处」是审阅可核性的一部分，不能因为有外部指针就删。正确做法：保留全部英文原句摘录，压体积改压①与正文重复的整段②同一口径在多处重复的措辞（导语/§三/§十/尾注四处重复的同一口径改成交叉指代）。若已删，用已审基线整条还原（本班从 receipts/d82-review-pkg-B.md 的内嵌主稿取回四条参考来源原文行）并重跑窄复审。
evidence: "evidence://v1/4998b8390482aa3c888b06a03caa757cba20b660611db150fcf9279fe5d89245（窄复审第 1 轮 VERDICT: FAIL, P0=0 P1=1，列 15 条 LOST）；evidence://v1/ceb6a6ad4c4e22dabd549d5d5a80aad7ea444aec6567525914ea84d5903726f1（第 2 轮仍 FAIL，另有交叉指代指错行）"
tags: [review, compression, traceability, promotion, citation]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-13T09:47:46.043697+08:00"
updated_at: "2026-11-13T09:47:46.043697+08:00"
---

复现与当前性验证：
- 当前性验证：grep -n '摘要原文含' docs/promotion/20261113-lfl-daily-82.md 应能看到四条参考来源各自的原句清单；若清单被删，窄复审会判 P1。
- 复现：把参考来源里正文未逐字引用的英文片段删掉后跑窄复审子代理（对比 receipts/d82-review-pkg-B.md 基线与现稿），P1 会从 0 变 ≥1。
- 本班实测：第 1 轮 FAIL(P1=1, 15 条 LOST)、还原后第 2 轮仅剩交叉指代指错行这一条 P1，修完即无 P1。