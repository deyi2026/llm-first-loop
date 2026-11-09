---
title: 改稿后必须重建审稿包再开下一轮审稿——审稿子代理读的是包里的主稿全文，不是磁盘上的主稿
scenario: LFL 每日推广发布链路：多轮独立审稿子代理对同一篇稿逐轮提修订、逐轮落地。审稿子代理的唯一输入是审稿包（docs/promotion/receipts/dXX-review-pkg.md），包内嵌主稿全文；正文改完后若不重跑审稿包生成器，下一轮子代理读到的仍是修订前的旧稿，会把已落地的修订全报「未落地」。本班（d71）第三轮即如此：把第一、二轮共 7 条已落地修订全报未落地，并给出 p1=7 的假阳性裁决，额外多花一轮审稿与一次重贴编辑器正文。
root_cause: ""
solution: 每次改稿后立刻重跑审稿包生成脚本（_dXX_reviewpkg.py），确认包内主稿全文与磁盘主稿 sha256 一致，再 spawn 下一轮审稿子代理；子代理任务书里显式写「本包已重新生成，是当前最新稿」。若某轮裁决与前一轮冲突，先查「包是否重建」而不是先怀疑稿件改动没生效：重建包后另开独立子代理全量复审，以新包读到的结果为准。
evidence: "本班实证：d71 第三轮审稿 subagent_46c9eac08deb 报 F1-F8/X1 全部「未落地」+ p0=1；重建审稿包（_d71_reviewpkg.py，pkg chars 28,526）后，第四轮 subagent_5709a1abf7e4 与第五轮 subagent_6e51eff1b43d 均逐条确认 F1-F8、X2 已落地并给出 PASS（p0=0 p1=0 p2=0）。回执：docs/promotion/receipts/d71-review-pkg.md、STATUS-20261108-daily71.md 第五节。"
tags: [promotion, review, article_publish, workflow, pitfall]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-08T13:48:09.760804+08:00"
updated_at: "2026-11-08T13:48:09.760804+08:00"
supersedes: [EXPERIENCE-20261105-改稿后必须重新生成审稿包-下一轮审稿子代理读到旧包会误判-修订未落地, EXPERIENCE-20261106-审稿包必须含主材料摘要原文-只收旁证摘要会让正文最核心一节无法在包内核验并直接产生-p1]
---