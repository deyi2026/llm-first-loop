---
title: 转述摘要的限定词时不得自行展开其含义：matched neutral note 不等于「同样长度、同样位置」
scenario: "LFL 推广 d89 晚班（2026-11-15）：论文摘要只写对照组是 \"a matched neutral note\"，正文自行展开成「一条同样长度、同样位置、但不包含正确值的备注」——「同样长度、同样位置」是摘要没有给的信息，属于替一手来源补细节。父级自查（对照 receipts/d89research/arxiv-2611.14654-verify.json 的 summary 原句）发现并改写。"
root_cause: 为了让读者看得懂，把含糊限定词补成了具体条件，而补的内容没有出处
solution: "转述论文限定词时只保留原词并注明「摘要没有展开 X 具体指什么」；要展开必须拿到一手全文并能指出出处，否则只能标为「本号理解」。审稿包里必须带上摘要原文全段（不是要点清单），才能被逐句核。当前性验证：改稿后逐句把正文里的英文引号片段与 `python3 -c \"import json;print(json.load(open('docs/promotion/receipts/d89research/arxiv-2611.14654-verify.json'))['summary'])\"` 输出的原文对照，确认每个引号片段逐字命中且没有任何摘要之外的展开描述。"
evidence: docs/promotion/receipts/d89research/arxiv-2611.14654-verify.json → summary 原句「from 51% under a matched neutral note to 66%」；正文 §三 改后为「对照组是「matched neutral note」（matched 中性备注，摘要没有展开 matched 具体指什么）——一条不含正确值的备注，读数 51%」
tags: [推广班, 论文引用, 限定词, 不得外推]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-15T20:30:31.212874+08:00"
updated_at: "2026-11-15T20:30:31.212874+08:00"
---