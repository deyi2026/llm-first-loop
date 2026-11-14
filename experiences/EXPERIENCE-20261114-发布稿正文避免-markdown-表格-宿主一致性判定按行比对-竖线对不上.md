---
title: 发布稿正文避免 markdown 表格：宿主一致性判定按行比对，竖线对不上
scenario: LFL 推广班在今日头条发布正文（md → md2html → 粘贴）时，宿主准入的稿件—页面一致性判定按「行」比对
root_cause: ""
solution: 发布稿正文不用 markdown 表格，改用 `- **名称**：读数` 列表；改完必须重跑本地预演再开准入
evidence: receipts/d85-precheck.json（改前 match_ratio=0.8942 / consistent=false，改后 0.951 / consistent=true）；docs/promotion/STATUS-20261114.md 跨班遗留⑪
tags: [promotion, toutiao, publish-gate, rule28, markdown]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-14T13:58:05.546956+08:00"
updated_at: "2026-11-14T13:58:05.546956+08:00"
---

场景：LFL 推广班发布前用宿主同款 `_comparable_lines` / `_manuscript_consistency` 本地预演稿件—页面一致性（match_ratio 阈值 0.9）。
实测（d85，2026-11-14）：正文含一个 markdown 表格（表头 + 分隔行 + 4 行数据）时，编辑器把表格渲染成真 <table>，页面文本里没有竖线；而判定函数清洗 md 行时只剥前导 `# > - + 数字 . 、 )）`，不剥 `|`，于是 6 行表格行全部 unmatched，match_ratio = 0.8942 < 0.9 → 宿主准入会被判不一致而拒。
解法：发布稿正文一律不用 markdown 表格，把表格改成 `- **名称**：读数` 形式的列表；同一篇改完复测 match_ratio = 0.951（未匹配只剩 5 行：标题行在 input 框内 + 4 条 md 图片行，与 d84 同因）。若必须保留表格，则先确认宿主判定对表格行做了归一化，否则不要用。
验证：docs/promotion/receipts/d85-precheck.json；STATUS-20261114.md 跨班遗留⑪。