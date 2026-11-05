---
title: 跨稿派生脚本必须逐项替换稿级常量（文件名/标题/图号/标签/卡片关键词）
scenario: LFL 推广每日班次的发布/自检脚本由上一班脚本复制派生（_d60_publish.py → _d61_publish.py 等），脚本里内嵌了上一班的标题、图号正则、标签统计名、卡片关键词与送审稿落盘文件名。
root_cause: ""
solution: |
  把上一班脚本复制成新班脚本后，必须逐项替换稿级常量再运行，至少查：①主稿/台账/HTML/会话/准入/送审稿文件名；②标题常量；③图号正则与 CAP_ORDER（图注 alt 的「图NNN」）；④标签统计用的标签名；⑤作品管理页卡片关键词；⑥送审稿落盘文件名。本班共 5 处，漏改任何一处都会让自检读到上一班的断言。
  当前性验证：grep -n 'daily6[01]\|图2[0-9][0-9]\|TITLE =\|CAP_ORDER\|tag_eval\|const t=' docs/promotion/_d61_publish.py，确认无 60 班残留且图号与主稿 alt 一致；再跑发布脚本 verify 阶段，caption_order 应为 图262/263/264/265。
evidence: "2026-11-05 d61 早班实测：_d60_publish.py → _d61_publish.py 共替换 6 类稿级常量（图号正则 258-261→262-265、CAP_ORDER、标签 #AI安全#→#AI评测#、卡片关键词、标题、送审稿文件名 daily60-manuscript-page.txt→daily61-manuscript-page.txt），并新建 d61_cards.js。"
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-05T08:52:43.586136+08:00"
updated_at: "2026-11-05T08:52:43.586136+08:00"
---