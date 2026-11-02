---
title: 引用本仓库对比报告的数字前必须回源文档核对：报告自身也有笔误（9B 工具名、README 引文、core/loop 口径）
scenario: 要引用本仓库既有分析报告/评审文档里的数字、代码行数、原文引语写对外稿件。
root_cause: ""
solution: 把「报告」当线索而不是事实源：每个进入正文的数字/引语回源文档或仓库实查（grep 计数、wc -l、sed 读原文），台账里写明出处与口径；发现报告笔误时在稿件中按源文档订正并留痕，同时把回改建议登记为待办。
evidence: "2026-10-31 独立审稿子代理（glm/glm-5.3）第一轮 REVISE，8 条 BLOCKING 中 2 条为报告自身笔误；逐条回源核对（context_health_review_2026-08-31.md grep 计数、README.md:11、wc -l core/loop/*.py）后全部订正，第二轮窄复审 PASS（16/16 RESOLVED，0 blocking）。"
tags: [fact-check, source-of-truth, report, article_publish, ledger]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T09:30:54.252736+08:00"
updated_at: "2026-10-31T09:30:54.252736+08:00"
---

场景：2026-10-31 依据《单主循环与子代理编排：Anthropic 立场与 LFL 架构的对比分析》（reports/LFL-vs-Anthropic-Subagent-20261031.html v1.1）写稿。独立审稿子代理核对 34/41 个数字后判定 8 条 BLOCKING，其中 2 条错在「报告本身」：§4.7.1 把 9B 量化模型误用的事件工具写成 execute_command，而源文档 docs/context_health_review_2026-08-31.md 实为 read_file(path="evidence://v1/…") 反复硬试（该文件 execute_command 命中 0 次、read_file 命中 11 次）；§3.1 把「没有 planner/router/SOP 阶段机」当成 README 原句，而 README.md:11 原文是「一个『AI 优先』（LLM-first）的 Agent 运行时（Harness）」。处置：正文/图/台账一律回源文档与仓库实查订正，并在台账里显式标注「报告笔误，按源文档订正」。另核对：core/loop 实为 16 个文件、合计 9198 行（最大几个 engine 2939/events 1467/runner 1018/build 892，其后 injection_span 823）。