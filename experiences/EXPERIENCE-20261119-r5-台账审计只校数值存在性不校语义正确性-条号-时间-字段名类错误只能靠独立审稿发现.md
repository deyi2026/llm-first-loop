---
title: R5 台账审计只校数值存在性不校语义正确性，条号/时间/字段名类错误只能靠独立审稿发现
scenario: "LFL 推广班次的 R5 台账审计（正则抽正文数值 → 子串匹配台账 → missing_in_ledger=[]）在本班全程报 PASS，却漏掉了多类只有语义核对才能发现的问题：热榜条号写成第 27/47 条（回执实为第 29/48 条）、热榜观测时间写成 08:11:54（回执 fetched_at=08:12:09）、台账出处写成不存在的字段名 hard_boundary_patterns / ai_rules.lines / tool_descriptions（回执实为 hard_boundary_pattern_count / ai_rules_lines / compact_tool_descriptions）、正文写「这条词表里没有公司名」而 tight_keywords 实含 OpenAI/Claude/字节/阿里/腾讯/英伟达、正文写两篇论文「未经同行评审」而第二篇 comment 写明已投稿 NAACL 2027 Industry Track。"
root_cause: ""
solution: "台账审计 PASS 不等于事实正确，必须另配独立审稿子代理做语义核对。落地做法：①台账每行的「出处」字段名一律从回执 JSON 实际键名派生（用脚本从回执取值写进台账，不手写字段名）；②凡是「同源不同口径」的序号/时间（热榜 rank 与 top50.txt 行号、fetched_at 与 _ran_at）做双源比对并统一到同一回执时间戳；③涉及论文元数据的断言（同行评审状态、投稿信息、主分类）先读 arXiv comment/journal_ref/primary_category 字段再落笔；④审稿包的兜底清单必须从回执字段派生，并在字段取不到值时视为脚本错误而不是「None 正常」。当前性验证：跑 receipts/d98research/_d98_audit_r5.py 仍应输出 AUDIT VERDICT: PASS；验证「审计不校语义」这一点可用 grep -n 'n not in ledger' receipts/d98research/_d98_audit_r5.py 看到判定只做子串匹配。"
evidence: "本班回执：docs/promotion/receipts/d98-audit.json（verdict=PASS、n_numbers=68、missing_in_ledger=[]、recheck 两项 found_in_source=true）；而 R1 内容审稿（subagent_b746da43bfeb）报 P0×1/P1×3/P2a×3、R1 来源审稿（subagent_801c640ee113）报 P0×1/P1×3/P2a×1/P2b×6、R2 内容审稿（subagent_aba5e9476b25）报 P0×1/P2a×1/P2b×6、R2 来源审稿（subagent_257242b30615）报 P0×1/P1×2/P2a×1/P2b×4；R3（subagent_96085b00ee19）判 PASS 无 P0/P1。"
tags: [promotion, R5, audit, ledger, review]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-19T08:48:21.567889+08:00"
updated_at: "2026-11-19T08:48:21.567889+08:00"
supersedes: [EXPERIENCE-20261109-r5-台账的数值-token-正则只覆盖数字型-中文数词形态的可核计数会整类漏检-必须显式补进台账, EXPERIENCE-20261111-r5-台账的出处括注必须与所引行原文一致-同一数值出现在多处要拆行分别登记]
---