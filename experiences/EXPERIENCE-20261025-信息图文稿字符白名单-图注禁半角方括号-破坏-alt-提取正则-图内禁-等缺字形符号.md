---
title: 信息图文稿字符白名单：图注禁半角方括号（破坏 alt 提取正则）、图内禁 ✓✗ 等缺字形符号
scenario: "LFL 推广稿：md 图片行 ![图注](path) 由自写构建脚本抽嵌 data-URI，PIL 中文字体 STHeiti 绘制图内符号"
root_cause: ""
solution: 图注白名单字符（无半角方括号）；图内符号用图形原语+汉字替代 ✓✗；构建前先 grep 图注行扫一遍方括号
evidence: "BUILD 首跑 md_img=3/resid=1 FAIL 诊断输出（grep NOMATCH 定位 fig168 行）；read_image fig165 首轮报缺字方框、圆点+过字修订后复验正常（2026-10-25 20:0x-20:2x）"
tags: [promotion, 信息图, md2html, 字符陷阱]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-25T21:07:03.469848+08:00"
updated_at: "2026-10-25T21:07:03.469848+08:00"
---

L39 两个字符级陷阱：①md 图注含半角方括号：fig168 图注写「CI[26,49]」，`]` 使构建脚本的 `^!\[([^\]]*)\]\(([^)]+)\)$` 不匹配，该图行整段漏嵌（md_img=3/4、resid=1、BUILD FAIL 一轮）。规则：**图注文案禁用半角 [ ]（区间改 26-49、括号用全角）**。②图内 ✓ 字形缺字：STHeiti 无 U+2713，d.text("✓") 渲染成空框（read_image 报「疑似字体缺字方框」）。规则：**中文画布图内符号只用图形原语（ellipse/line）+汉字**（绿圆点+「过」），不用 ✓✗⚠ 等符号字形；发布侧平台还会剔除部分 emoji，图形原语不受影响。当前性验证：grep -c '\\[' docs/promotion/20261025-lfl-daily-39.md 的图注行应为 0（正文区间写法 26-49）；grep -n 'd.ellipse' docs/promotion/figures/_d39.py 应命中 fig165 圆点替代。