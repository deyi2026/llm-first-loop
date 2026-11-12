---
title: 派生稿级脚本时 sed 替换覆盖不全（daily-NN/figNNN/PGC ID），首跑收口 FAIL 才暴露
scenario: LFL 推广 d80 收口：`_d80_closeout.py` 由 `_d79_closeout.py` 用 sed 's/d79/d80/g' 派生，稿级常量未全量替换导致首跑 CLOSEOUT_VERDICT=FAIL。
root_cause: sed 替换模式 `s/d79/d80/g` 只覆盖 `dNN` 前缀式标识符，未覆盖 `daily-NN` 文件名、`figNNN` 图号、`图NNN` 图注前缀、PGC ID、平台时间等其它稿级常量写法；派生后未立即跑一次自检，缺陷直到收口跑完才暴露。
solution: "派生后立即 grep 全部稿级常量位（文件名 daily-NN、md 名 lfl-daily-NN、figNNN 图号、图注「图NNN」、PGC ID、平台时间、标题串、标签串、TAG 计数）逐项核对，再跑一次；更好的做法是派生脚本顶部集中一个 `DRAFT = \"80\"` 常量，其余全部由它派生，杜绝散落硬编码。"
evidence: "docs/promotion/receipts/d80-closeout.json（首跑 fails=[imgs_match, caption_order_ok]，修正后 CLOSEOUT_VERDICT=PASS、fails=[]）；首跑与修正后两次命令回执（同日 14:44–14:46）；docs/promotion/STATUS-20261112-daily80.md §八.8"
tags: [promotion, derived-script, constant-propagation, closeout, fail-closed]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-12T15:19:37.569218+08:00"
updated_at: "2026-11-12T15:19:37.569218+08:00"
supersedes: [EXPERIENCE-20261105-跨稿派生脚本必须逐项替换稿级常量-文件名-标题-图号-标签-卡片关键词]
---

scenario: LFL 推广 d80 由 d79 的收口脚本 `_d79_closeout.py` 派生为 `_d80_closeout.py`，用 sed 's/d79/d80/g' 替换。首跑 CLOSEOUT_VERDICT=FAIL：fails=[imgs_match, caption_order_ok]。

solution: 定位到第 8 行 `MD = ROOT / "docs/promotion/20261112-lfl-daily-79.md"` 未被替换——因为文件名里的日期段是 `daily-79`（连字符+数字），不是 `d79`（前缀+数字），sed 的 `s/d79/d80/g` 匹配不到。改为显式替换后复跑 PASS。教训：派生脚本的稿级常量不止存在于 `dNN` 形式的标识符里，也存在于 `daily-NN` 形式的文件名、图号 `figNNN`、图注 `图NNN`、PGC ID、平台时间这些位置；本次图号（335-338→339-343）与 PGC ID 是靠后续 edit_file 单独改的，若只跑 sed 就会留下图注顺序与 PGC ID 两处错值。

适用边界：适用于所有从上一班脚本派生的稿级脚本（build/audit/closeout/public_verify/poll）。