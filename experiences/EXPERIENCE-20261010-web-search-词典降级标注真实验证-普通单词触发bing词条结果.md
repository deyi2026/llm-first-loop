---
title: web_search 词典降级标注真实验证：普通单词触发bing词条结果
scenario: web_search 词典降级标注（EVO-20260910-528ab2f3 修复，commit 692aef752）上线时只有 mock 单测证据，没有运行态真实降级样本；若检测条件在真实 bing 返回下不触发，修复等于没生效。
root_cause: ""
solution: "用无词条意图的孤立普通词（如 production）打 general 通道：真实触发路径为 bing 返回大量词典站结果（剑桥词典/iciba/百度百科词条页）。验收三点：(1) 回执含 [词典降级] 与 degraded_backend=bing_dictionary_fallback 标注；(2) header（[query]/[backend]/[count]）与结果行原样保留；(3) query 含词条意图标记（意思/翻译/发音/definition of 等）时豁免不标注。"
evidence: "本会话 2026-10-10 21:53 web_search(query=\"production\", channel=general, limit=5) 回执原文含 \"[词典降级] degraded_backend=bing_dictionary_fallback\" 与完整 5 条结果；commit 692aef752（单测 test_web_m48.py 31/31）"
tags: [web-search, dictionary-fallback, receipt-annotation, live-verification]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-10T21:55:37.989065+08:00"
updated_at: "2026-10-10T21:55:37.989065+08:00"
---

EVO-20261010-528ab2f3（commit 692aef752）上线当晚即用真实样本验证：query="production"（单词、无词条意图标记）走 general 通道，bing 返回 2 条 dictionary.cambridge.org + 1 条 iciba + 2 条百度百科词条页 → 回执第二行出现 "[词典降级] degraded_backend=bing_dictionary_fallback: 结果疑似词条解释而非正常网页检索（零有效信源风险）。建议改写 query（专有名词/品牌词开头，去掉孤立常用词）后重试"。结果 5 条完整保留（契约：不改变返回结构），模型可据此自行决定改写重试。触发词参考：production/端/具等孤立常用词。当前性验证：再跑一次 web_search(query="production", channel=general, limit=5)，回执应含 [词典降级] degraded_backend=bing_dictionary_fallback 且 [count] 5 条结果完整保留。