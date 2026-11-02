---
title: 抓取页面里作者名与正文分行：只摘正文会把帖子张冠李戴
scenario: LFL 推广稿件引用今日头条话题页/社媒页实读文本作为事件来源。
root_cause: 页面 innerText 的版式是「作者名+时间 → 关注 → 正文」，作者名属于上一块的尾部、属于下一块的开头；只按位置截取正文片段会把它挂到错误的账号名下。
solution: 实读页面的作者名与正文必须成对摘录进审稿包/台账（保留「作者名+时间行」与正文的版式顺序），发布前用原文对齐一次归属；无法确定全称时在正文用平台可见写法并标注为二手账号名。当前性验证：grep -n '溯金川' docs/promotion/receipts/d54research/trending_token_text.txt 与 grep -n '万象互联' 同文件，两条作者名各自紧邻的正文块必须与正文表述一致。
evidence: 源抓取落盘 docs/promotion/receipts/d54research/trending_token_text.txt；正文修订前后对照见 docs/promotion/20261102-lfl-daily-54.md 第 9 行与台账 20261102-daily-54-sources.md 第 14 行；首审子代理 subagent_86fa636bc6df 判 P0-1。
tags: [promotion, 实读, 话题页, 作者归属, 张冠李戴]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-02T20:30:47.763958+08:00"
updated_at: "2026-11-02T20:30:47.763958+08:00"
---