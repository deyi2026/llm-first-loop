---
title: 头条 ProseMirror 带图注入的 6 个坑与「先传 CDN 再整篇粘贴」可靠流程
scenario: 今日头条编辑器带图注入：盲扫工具栏、遮罩吞点击、setFileInputFiles nodeId 失败、图片计数翻倍
root_cause: ""
solution: 按上述六条坑与两段式流程执行：面板打开前不要点正文；统计按可见性过滤；优先用「上传取 CDN → 整篇粘贴」避免逐图定位。
evidence: 2026-10-11 D06 实战：6 张 fig22/23/24 上传取 CDN，正文 2563 字、3 张可见 1200×720、3 条图注、边界声明保留，提交 PGC 7695218207455707682；回执 receipts/20261011-daily06-submit.json sha256=4d387d89f82316fed20ea239513393cc45209f3b154fe5d3a10a46b851f41b2c
tags: [toutiao, CDP, ProseMirror, 发布, 配图]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-11T09:39:36.529303+08:00"
updated_at: "2026-10-11T09:39:36.529303+08:00"
---

当前性验证：执行 `grep -c 'syl-toolbar-button' <编辑器页脚本>` 无法离线复核，改用运行时复核——在头条编辑器页 evaluate `document.querySelectorAll('.syl-toolbar-button')[11].click()` 后若 `document.querySelectorAll('input[type=file]').length>0` 则入口仍是第 12 个；图片计数复核用 `[...document.querySelectorAll('.ProseMirror img')].filter(i=>i.offsetParent!==null).length` 应等于稿件配图数而非 2 倍。