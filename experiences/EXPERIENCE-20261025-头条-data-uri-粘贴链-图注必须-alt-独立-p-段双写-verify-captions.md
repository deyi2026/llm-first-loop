---
title: 头条 data-URI 粘贴链：图注必须 alt+独立 <p>段双写（VERIFY captions 检测正文块，仅 alt 计 0）
scenario: 头条图文 data-URI 粘贴发布链（md2html 自写构建 + ClipboardEvent paste + VERIFY GATE captions 计数）
root_cause: ""
solution: 构建脚本图片行输出 img 块+图注文本块两段；发布前本地先自检 html 含 N 个 <p>图xx｜ 开头段
evidence: "首次 verify 输出 GATE FAIL（captions:0）+ _d39_blocks.js 读编辑器块结构（DIV 图块无 alt）；修订 build 后 STATE_AFTER captions=4、VERIFY GATE PASS（2026-10-25 20:5x）"
tags: [promotion, 头条, 发布链, data-URI]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-25T21:07:20.835575+08:00"
updated_at: "2026-10-25T21:07:20.835575+08:00"
---

d39 首次 VERIFY GATE FAIL 于 captions=0：自写构建脚本把图注只写进 `<img alt="图16x｜…">`，头条编辑器粘贴后图片块是 DIV（含 2 个 img + 编辑/搜图按钮，无 alt 透出），VERIFY 的 captions 检测的是编辑器**正文直接子块**中以「图16x｜」开头的文本块——只有 alt 时计数为 0，必须 reload 重粘贴。规则：**构建 HTML 时每个图片生成两个块：`<p><img src="data:…"/></p><p>图注全文</p>`（alt 与独立文本段双写）**；alt 供发布后图片描述，独立段供编辑器 VERIFY 与页面图注。修复后 captions=4、VERIFY GATE PASS（chars 4890→5577 的差即 4 段图注文字）。当前性验证：grep -c '<p>图16' docs/promotion/receipts/20261025-lfl-daily-39.html 应为 4。