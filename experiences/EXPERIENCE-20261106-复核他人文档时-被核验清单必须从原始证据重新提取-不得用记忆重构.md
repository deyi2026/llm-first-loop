---
title: 复核他人文档时，被核验清单必须从原始证据重新提取，不得用记忆重构
scenario: 审查一份第三方审计文档（LFL_Computer_Browser_Audit_Requirements_Design_2026-11-06.md）。文档 §2.2 声称跑了 12+5 个测试文件。我在复核时凭阅读印象拼出一组文件名（test_desktop_m1_perceive.py 等）去 find/ls 核验，全部不存在，于是断言「文档测试清单虚构」并一度把该指控写进了修订稿。
root_cause: ""
solution: 回查本会话 read_file 原始证据 blob 后发现：原文 §2.2 从未列出文件名，12+5 文件的真实清单在 §8.1 的命令块里且全部真实存在；按原文逐字复跑得 263 passed / 161 passed + 2 skipped，与文档一致。撤销指控、恢复原文、在修订记录中留痕。正确流程：(1) 核验清单先 grep 原文拿到逐字清单再比对文件系统；(2) 「文档造数」级指控必须先完整复现文档声称的命令（逐字），复现失败才可下结论；(3) 指控写入交付物前必须有原始证据引用。
evidence: "本会话证据链：evidence://v1/27b32b65...（原始文档全文，§2.2 无文件名、§8.1 真实清单）；批次一复跑 263 passed 1.97s（evidence://v1/83efd1b5...）；批次二 161 passed+2 skipped（evidence://v1/2c636674...）；§8.2 复现 satisfied=True（evidence://v1/e1f084d2...）；文档 §10 修订记录第 4 条留痕。"
tags: [复核纪律, 证据提取, 反幻觉, 文档审查]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-06T11:50:07.245333+08:00"
updated_at: "2026-11-06T11:50:07.245333+08:00"
---