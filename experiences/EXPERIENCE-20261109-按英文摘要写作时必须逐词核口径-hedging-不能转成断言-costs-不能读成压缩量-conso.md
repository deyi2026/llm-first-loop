---
title: 按英文摘要写作时必须逐词核口径：hedging 不能转成断言、costs 不能读成压缩量、consolidation 与 compression 不能混用
scenario: LFL 推广班次写稿/改稿时，论文摘要的英文原词直译口径出错（2026-11-09 早班 d73）
root_cause: ""
solution: 把摘要里的每个英文原词逐个回原文核三类口径：hedging 语气（can/reducing the risk that）必须保留限定词、名词口径（costs≠压缩量、utility≠准确率、oracle≠可交付方法）、同指术语统一（consolidation/merge/compressing memory 统一为一个中文词并在首次出现处声明，论文原词放括注）。
evidence: 本班审稿条目：包 A 第 2 条与第 4 条、包 A 终轮必查回应、包 B 第 12 条；摘要原句 alongside its costs（实读 arXiv API 返回的 2611.03930v1 摘要）；改稿后复审 PASS
tags: [写稿, 论文摘要, 口径核对, 夸大, 推广班次]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-09T08:56:01.581022+08:00"
updated_at: "2026-11-09T08:56:01.581022+08:00"
---

场景：2026-11-09 早班 d73，稿子经 5 轮独立审稿，其中 4 条**实质**问题全部出在英文原词的直译口径上：
① 摘要 "reducing the risk that frequently retrieved memories crowd out…"（降低风险）被写成断言「会把…挤掉」；
② 摘要 "evaluate memory compression by the task utility it preserves alongside its costs"（成本账）被写成「而不只是看它压掉了多少」（读成压缩量）；
③ 摘要 "consolidation / merge / compressing memory" 指同一道合并工序，正文有的地方写「合并」、有的地方写「压缩」，与另一篇讲上下文压缩的论文撞词；
④ 图注把 "can silently destroy" 的 can 漏掉。

解法：写稿和改稿时，把摘要里每个英文原词逐个回原文核三件事——(a) 语气词：can / may / reducing the risk that / tends to 这类 hedging 必须落到中文（保留「可能/风险被压低/通常」），不得转成断言；(b) 名词口径：costs 是成本账不是压缩量，utility 是效用不是准确率，oracle 是不可得参照不是可交付方法；(c) 同指术语：摘要用几个词指同一件事，正文就要统一用一个词并在首次出现处声明，并把论文原词放在括注里与别的语境区分。
核对清单可做成审稿包的「数字核对表」同款：把关键英文原词连同其中文对应写法列成表，让审稿人逐条比对。

适用边界：只对「按摘要写作」的稿件适用；本文不引用原文全文时尤其要小心（只读摘要更容易把 hedging 丢掉）。