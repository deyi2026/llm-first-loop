---
title: "审稿包体积必须按子代理模型的输入预检预算切分：MiniMax-M3.1-Flash 子代理预算实测 31,698 字符，42K 单包连挂三次"
scenario: LFL 推广班次的独立审稿子代理因审稿包过大而连续预检失败（本班 2026-11-09 早班 d73，MiniMax-M3.1-Flash 子代理）
root_cause: ""
solution: 按子代理模型的输入预检预算切包：拆成两个各含主稿全文的小包（各 15–20K 字符），任务书压成清单式短行，显式禁用检索类工具并规定「只调一次 read_file」；两个子代理并行各审一包。
evidence: "子代理失败回执（投影 33,266 / 42,855，预算 31,698）；成功回执 tools=1；receipts/d73-review-pkg-a.md 19,362 字符、d73-review-pkg-b.md 15,400 字符；本班 8 次审稿子代理全部 completed"
tags: [审稿子代理, 上下文预检, 拆包, MiniMax, 推广班次]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-09T08:55:59.669452+08:00"
updated_at: "2026-11-09T08:55:59.669452+08:00"
---

场景：2026-11-09 早班 d73，用 minimax/MiniMax-M3.1-Flash 子代理做独立审稿。单包审稿材料 42,104 字符，连挂三次：
① 首次子代理自行调用 search_records/search_archive/list_evidence 检索经验库，输入投影推到 42,855 字符；
② 改为「任务书+只读该包」后单次 read_file 返回全包，投影 33,266；
③ 改为分段读 3 次（offset/limit）后累计投影仍 42,855。
三次均以「子代理上下文预检：最小无损投影仍超过该模型输入容量（预算=31698字符）」失败；该模型的子代理输入预检预算实测约 31,698 字符。

解法：把审稿材料拆成两个小包，各含主稿全文——包 A（事实一致性：主稿+四篇 arXiv 摘要原文+数字核对表+15 条清单）19,362 字符、包 B（合规与结构：主稿+LFL 源码静态读数+台账 src 行+图注机检/R5 回执+15 条清单）15,400 字符；任务书写成清单式短行（禁复制大段清单进任务书），并显式写「只调一次 read_file、禁止 search_records/search_archive/list_evidence/search_evidence/web_*/execute_command/read_image、禁止读第二次」；两个子代理并行、每包各一个。此后 8 次审稿子代理全部 tools=1 一次读完，无一失败。

适用边界：预算值随子代理模型而变（MiniMax-M3.1-Flash 实测 31,698 字符）；换模型需重测。若审稿材料天然可分（主稿+材料），优先拆包而不是压内容；清单与要点放任务书会放大投影，放包内更省。