---
title: md2html 图片 alt 必须写图注文案，否则正文出残段
scenario: "宣传稿流水线（md → md2html → 头条/知乎 CDP 注入）：md 图片写成 `![figNN](path)`，alt 是短代号"
root_cause: ""
solution: "md2html 不处理图片语法，`![]()` 走「链接剥壳保留文字」规则后 alt 成为正文残段（头条发布后才被发现，需编辑页二次手术）。规范：md 图片 alt 必须直接写图注文案（如 `![示意：心跳协议——…](path)`）。发布前双重校验：(1) 结构不变量——md 图片数 == HTML `<img` 标签数，不等即转换器丢了图；(2) 残段扫描——grep '<p>fig' 零命中。只做 (2) 不够：若 alt 恰好不含 fig 前缀，残段扫描会假阴性"
evidence: receipts/20261012-daily10-submit.json 的 post_publish_correction 与 STATUS-20261012.md「本轮关键事故」记录了完整根因与修复；两 HTML grep '<p>fig3' 计 0；重提交后公网页 stray_fig=0
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-12T19:51:04.967638+08:00"
updated_at: "2026-10-12T19:51:04.967638+08:00"
---

头条发布后发现正文残留 fig33/fig34 纯文本段。根因：md2html.py 无图片语法处理，`![alt](path)` 经「链接剥壳」保留 alt 为正文。修复：编辑页 execCommand('delete') 删残段+重提交，且 md 规范改为 alt 写图注。验证：grep -c '<p>fig3' 两 HTML 均 0；公网页 stray_fig=0。回执 receipts/20261012-daily10-submit.json post_publish_correction 节