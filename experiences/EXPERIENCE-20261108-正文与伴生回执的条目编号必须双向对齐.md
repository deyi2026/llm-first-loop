---
title: 正文与伴生回执的条目编号必须双向对齐
scenario: LFL 推广 d72 晚班（2026-11-08）：伴生回执 receipts/d72-lfl-static-readings.txt 的小节顺序按源码位置排（第三条=_diagnose_mismatch 逐维指名、第四条=切片 PASS 授权整树执行面），而正文第十节按叙述顺序列举（第三条=切片 PASS、第四条=_diagnose_mismatch）——同一个「第 N 条」在两处指两件事。第五轮独立审稿子代理抓为 P2：「正文第三/四条次序与第三节标题编号互换」。
root_cause: 伴生回执是按「读到源码的顺序」写的，正文是按「叙事顺序」写的，两套顺序没有做映射就分别打包；条目标题本身互不冲突，只有编号冲突，人眼通读两处时不容易发现。
solution: |
  正文用「第 N 条」列举条目时，伴生回执与审稿包里的同名编号必须逐条对应；打包时按正文的叙述顺序排列节选，不要按源码位置或发现顺序排；交审稿前做一次机械对照（正文第 N 条 ↔ 回执第 N 条），只靠肉眼易漏。
  当前性验证：复现命令 `grep -n '^### 第' docs/promotion/receipts/d72-lfl-static-readings.txt` 得六条小节标题，再逐条与正文 docs/promotion/20261108-lfl-daily-72.md 第十节的「第一条…第五条」标题比对，应一一对应；本班第六轮审稿子代理 subagent_ea741926e4f8 即按此对照确认通过。
evidence: docs/promotion/receipts/d72-lfl-static-readings.txt（第一至第六条小节标题顺序）；审稿第五轮子代理 subagent_bd360f93965f 的 P2 结论；修订后回执第三/四条已互换并与正文第十节一一对应，第六轮子代理 subagent_ea741926e4f8 确认通过。
tags: [LFL推广, 编号对齐, 交叉引用, 审稿P2, d72]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-08T20:36:07.512451+08:00"
updated_at: "2026-11-08T20:36:07.512451+08:00"
---