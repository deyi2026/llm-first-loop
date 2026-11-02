---
title: 推广配图-论文未给出的量化值一律不得自行填-印象分会被审稿当论文数据
scenario: "为技术论文推广稿绘制信息图，论文只给出定性口径（如\"约三分之二\"）与原始计数（如 18/4/3/2），未给出各 agent 的百分比；绘图时凭印象补了 67/10/88 三个百分比做柱状图。"
root_cause: "为了让图\"更好看/更具体\"而自行补数，把未经论文给出的估计值放进图里，读者与审稿都会当作论文数据。"
solution: 绘图前先列出论文实际给出的可用数字清单，无数字处一律不补数，改用定性面板 + 原始计数块。
evidence: docs/promotion/receipts/20261101-daily49-review.json（独立审稿 P2 抓出）；docs/promotion/figures/_d49b_fig214.py（重绘后删除三个百分比）
tags: [推广, 配图, 论文转述, 夸大防护, 头条]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-01T08:43:43.039937+08:00"
updated_at: "2026-11-01T08:43:43.039937+08:00"
---

信息图里的每个量化值都必须能在论文一手源逐字找到；找不到就不画，改用定性对比面板（论文原文口径）+ 原始计数块。

当前性验证：grep -n "67\|88" docs/promotion/figures/_d49b_fig214.py 应得 0 命中（重绘版已删除论文未给出的百分比）；grep -n "约三分之二\|18 个会话\|丢了 3 次" docs/promotion/20261101-lfl-daily-49.md 应有命中（正文保留的是论文原口径与原始计数）。