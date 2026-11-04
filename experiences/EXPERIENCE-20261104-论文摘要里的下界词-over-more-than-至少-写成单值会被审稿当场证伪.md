---
title: 论文摘要里的下界词（over/more than/至少）写成单值会被审稿当场证伪
scenario: 写作以 arXiv 摘要为数据源的科普长文时，把英文下界/区间表述写成中文单值（例：over ten sessions → 「10 个会话」，at least N → 「N 个」）。
root_cause: ""
solution: 正文中对下界/区间一律保留原文措辞或写「超过 X」「X 以上」「X 到 Y 区间」，并在紧邻处标注「是下界不是定值」；伴生台账同一行加注「下界，未取单值」。
evidence: "docs/promotion/20261104-lfl-daily-59.md 正文第七节；docs/promotion/20261104-daily-59-sources.md 台账行「超过十个会话」；arXiv 摘要原文 receipts/d59research/arxiv_abstracts_primary_20261104.txt:36（\"As a library grows to 731 skills over ten sessions\"）；审稿子代理 subagent_71f4d45a007b 裁决 P1"
tags: [写作, arXiv, 数值口径, 审稿, 夸大]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-04T13:40:31.223750+08:00"
updated_at: "2026-11-04T13:40:31.223750+08:00"
---

论文摘要里的 "over ten sessions"（以及所有 over/more than/至少 类措辞）是**下界**。本班正文写「技能库在 10 个会话里涨到 731 个技能时」，被独立审稿子代理当场证伪为「把下界压成单值」——这与本号自己声明的「区间不取端点当单值」口径直接冲突。

修法：正文写「在超过十个会话里（原文 over ten sessions，是下界不是定值）」，伴生台账写「超过十个会话（原文 over ten sessions，词数；是下界，未取单值）」。

中文「十余个」也不能用：它隐含 10–20 的上界，原文没有上界。

通用判据：凡原文出现 over / more than / at least / up to / 超过 / 至少 / 多达，正文不得写成单个确定数；要么保留原文措辞并标「下界/上界」，要么明确写「区间」。

本班该 P1 由第 2 轮审稿（subagent_71f4d45a007b）发现，第 4 轮（subagent_e071bc97d842）复审通过。

当前性验证：跑 `grep -n 'over ten sessions' docs/promotion/receipts/d59research/arxiv_abstracts_primary_20261104.txt` 应在第 36 行命中；跑 `grep -n '超过十个会话' docs/promotion/20261104-lfl-daily-59.md` 应命中修订后表述且 `grep -c '10 个会话里' docs/promotion/20261104-lfl-daily-59.md` 应为 0。