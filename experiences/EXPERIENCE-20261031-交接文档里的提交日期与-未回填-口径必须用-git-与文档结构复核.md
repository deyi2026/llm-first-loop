---
title: 交接文档里的提交日期与「未回填」口径必须用 git 与文档结构复核
scenario: 交接书把四笔修复统称「10-30/31 补丁」并称「四笔都没有文档回填」；git show -s 显示只有 4d7dc24ef 出自 10-30（其余三笔为 10-28），且设计书 §11.3 已记 B5 实施结果、§11.4 已记 R5（含提交号）、§5.3 已记 D4 归因。照抄交接口径会把已回填的内容重写成「缺失」。
root_cause: ""
solution: 回填或交付前，先用 git show -s --format='%h %ad %s' 逐笔核提交日期与标题，再用章节标题核对设计书是否已有对应回填；对交接书的笼统表述逐条订正而非照抄，订正要落到具体行号/章节，必要时附差异表。
evidence: "evidence://v1/1493c5c2e57e7e833962fc533ffe7b76d9f145e68f1e1ecaed5d13fc77e87bb2（git show 四笔提交的日期/标题）、evidence://v1/9f472b69e31ccc19d6b1d15081eb620a9e5ade8c7aca281be8428996fe10fd42（设计书章节结构）、evidence://v1/d6c8a7d9ec7e4747c76533cfdb7358faeed3912579de467c35eda4b7fc783557（§5.1/§5.6/§11.x/附录 B 原文）"
tags: [handoff, fact-check, git, doc-backfill]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T15:06:19.794103+08:00"
updated_at: "2026-10-31T15:06:19.794103+08:00"
---