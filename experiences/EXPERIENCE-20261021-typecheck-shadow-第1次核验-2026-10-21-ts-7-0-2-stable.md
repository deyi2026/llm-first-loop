---
title: "typecheck:shadow 第1次核验（2026-10-21）：TS 7.0.2 stable 已发布，shadow 样本仅1次，暂缓接入构建链"
scenario: "typecheck:shadow 定时跟踪（sched-f5536c3c，每2周×6次，工作目录 /Users/yyj/Project/llm-first-loop-mirror）触发条件核验"
root_cause: ""
solution: "按完成判据汇总了 shadow 数据并给出\"暂不接入构建链\"评估报告；触发条件(1) typescript 7.x stable 已成立且不会回退，后续次数无需重复完整评估，只增量核对 shadow jsonl 新记录与 tsrs 版本变化"
evidence: npm view typescript/tsrs dist-tags 回执（本 run）：typescript latest=7.0.2 stable；tsrs latest=0.18.0-ts7.1.0-dev.20260929 未变；webui/.typecheck-shadow.jsonl 共 1 行
tags: [sched-f5536c3c, typecheck-shadow, tsrs, typescript-7, recurring-task]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-21T12:37:13.890945+08:00"
updated_at: "2026-10-21T12:37:13.890945+08:00"
---

2026-10-21 第1次核验（effect_id=schedule:sched-f5536c3c:1）：npm registry 上 typescript latest=7.0.2（2026-07-08 发布，无预发布后缀）→ 触发条件(1)成立；tsrs latest 仍为 0.18.0-ts7.1.0-dev.20260929，无 -b 支持 → 条件(2)未成立。webui/.typecheck-shadow.jsonl 仅 1 条记录（commit 0193ace46，agree=true，tsc5.9.3 1398ms/0err vs tsrs 130ms/0err）。评估结论：样本 1 次且为 0-error 单 commit 快照，不足以证明错误捕获一致性，暂不接入构建链；建议门槛 ≥20 次含类型变更的零分歧，或优先评估升级 typescript@7.0.2 stable（正路）。后续核验可跳过重新评估，只需确认 shadow 记录是否新增。