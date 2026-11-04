---
title: 审稿子代理给出的源码行号必须自己 grep/awk 复核到当前文件再改稿
scenario: 独立审稿子代理对稿件里「引用自己仓库代码并标出行号」的段落提出行号修正
root_cause: 审稿子代理按自己读到的片段给行号，可能偏移或给到函数内某一行（如把 docstring 行当成实现行）；仓库文件在审稿与改稿之间也可能变动
solution: 逐条用 awk/grep 打到当前源码文件确认真实行号与函数范围，再据实改稿；不要照抄审稿意见里的行号
evidence: docs/promotion/STATUS-20261103-daily55.md 第六节 R3/R4/R6：store.py 734→732-756（733 文档字符串、745-750 字段）、action.py 195-202→197-215 与 52-57、privacy.py 17-27→17-26、desktop_perceive.py 452→452-460；均以 awk 打当前文件复核
tags: [review, line-number, fact-check, writing]
source:
  note: d55 早班实测
  work_unit_id: daily55-publish
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-03T09:56:51.283345+08:00"
updated_at: "2026-11-03T09:56:51.283345+08:00"
supersedes: [EXPERIENCE-20261102-引用自己仓库的行号必须-grep-n-实测-凭印象写会整段偏移]
---