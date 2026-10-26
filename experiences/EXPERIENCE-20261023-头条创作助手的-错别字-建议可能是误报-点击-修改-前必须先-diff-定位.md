---
title: 头条创作助手的「错别字」建议可能是误报，点击「修改」前必须先 diff 定位
scenario: 头条图文发布收口阶段，创作助手 AI 检测面板报「1 处错别字」并给出「个→各」的替换建议（面板同时报「共 2 条建议」）。若直接点「修改」，平台会把标题改成「26 各子代理会话全被拒之后」这种不成句的结果。
root_cause: ""
solution: |
  不要盲点平台的「修改」。正确做法：① 先 Runtime.evaluate 取编辑器 .ProseMirror innerText 存为 before；② 点平台的「修改」；③ sleep 后再取 after；④ difflib.SequenceMatcher 求 opcode，diff 为空说明被改的不是正文。定位到是标题被改后，用发布脚本的同一 setter 把标题按原文回填，再跑一次 verify gate 确认 title 与 MD 首行精确一致。
  
  当前性验证：复现命令 `python3 _p31_full.py verify` 应得 `GATE PASS` 且输出 `"title": "26 个子代理会话全被拒之后：LFL 把执行权做成了两道闸"`（与 20261023-lfl-subagent-governed.md 首行一致）；若标题被平台改写，该 title 字段会显示「26 各…」，据此判定是否需回填。
evidence: 本次实测：平台误报把「26 个子代理会话」改成「26 各子代理会话」；编辑器正文 before/after diff 为空（正文未被动），仅标题 input.value 被改；按原文回填标题后 verify gate 再次 PASS（title 与 MD 首行一致），最终作品管理列表首条标题正确、计数 45→46。
tags: [头条, promotion, diff, typo, publish, CDP]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-23T06:49:49.301266+08:00"
updated_at: "2026-10-23T06:49:49.301266+08:00"
---