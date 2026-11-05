---
title: 审稿意见与一手原文冲突时以一手原文为准：回执节选是审稿判断的事实底座，误判不得直接改稿
scenario: 多轮内容审稿中，某条审稿意见依据的是本方整理的「事实回执节选」，而节选本身没有覆盖论文摘要的相关句子，于是审稿人把「摘要原文本来就写了」的内容判成「回执外扩写/越界归因」，并给出删除建议；若照此改稿，会在稿子里写进一句假话（本班即把 CASEL 的五要素+六动作删掉并写成「摘要没有展开清单」）。该错误由另一名审稿人读取完整摘要原文后证伪。
root_cause: ""
solution: |
  1) 审稿意见只提供线索，不提供事实：以一手原文（论文摘要/官方文档/源码）为准，回执节选仅是本方视角的投影。2) 若一条意见会删除或改写正文中的事实性内容，改稿前必须回读一手原文；无法回读时不得按意见删事实，只能标注存疑。3) 发现节选漏句后，把该原句补进事实回执（新增 F 行）并在数据台账补对应行，使下一轮审稿人拿到完整底座。4) 多名审稿人结论冲突时，把冲突点与原文一起作为事实记录，再改稿；不得按票数取舍。5) 审稿意见与本方回执冲突这件事本身要写进当班回执，留痕可追溯。
  当前性验证：grep -n "We introduce CASEL" docs/promotion/receipts/d60research/arxiv_abstracts_d60.txt 应命中 CASEL 摘要原句（证明原文确有五要素与六动作）；grep -n "^\[F12\]" docs/promotion/receipts/d60research/facts_d60.txt 应命中补录行；grep -n "校准后的失败概率" docs/promotion/20261104-lfl-daily-60.md 应命中回改后的正文。
evidence: "d60 晚班（2026-11-04，sched-3e4a1e65:3）：审稿人B 依 facts_d60.txt F07 的节选（从 \"threshold and a trajectory risk ledger\" 起）判定 §七「五要素 + 六种动作」为回执外扩写；本班据其意见删除该段并写成「具体动作清单摘要没有展开，本文不逐项转述」——这是错述。审稿人A 读取 arxiv_abstracts_d60.txt 中 CASEL（arXiv:2610.36570）摘要原句 \"We introduce CASEL ... combines calibrated failure probability, state-dependent consequence, reversibility, ambiguity, and evidence freshness to choose, for each proposed tool call, among direct execution, verification, sandboxing, clarification, approval, and abstention by minimizing a per-mode cost.\" 后判定原文确有该内容，主稿回改并把该句补为 F12、台账补一行。回执：docs/promotion/receipts/d60-review-compliance.json、d60-review-facts.json、d60-review-fixes.md、facts_d60.txt:12。"
tags: [推广班次, 审稿, 事实回执, arXiv, 口径, 回执节选]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-04T20:52:23.388891+08:00"
updated_at: "2026-11-04T20:52:23.388891+08:00"
---