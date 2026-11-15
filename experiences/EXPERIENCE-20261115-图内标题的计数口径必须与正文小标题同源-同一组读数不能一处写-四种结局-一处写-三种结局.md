---
title: 图内标题的计数口径必须与正文小标题同源：同一组读数不能一处写「四种结局」一处写「三种结局」
scenario: LFL 推广 d89 晚班（2026-11-15）：图383 的图内标题写「同一份正确信息，四种结局」（按 4 个读数点 66%/44%/28%/49% 数），正文 §三 小标题写「三组读数：同一份正确的信息，三种结局」（按 3 组实验：诚实的备注 / 把「已完成」写进历史 / 成功回执 数）。同一组论文读数在图与文里给出两个结局计数，R1 独立审稿子代理判 P2a（图内数字与正文口径冲突），必须处置。
root_cause: 图与文各自按最顺手的维度计数，图内标题的计数维度没有回绑到正文小标题的计数维度
solution: "画图前先定「按哪个维度数」，然后把同一套计数措辞同时写进：正文小标题、图内标题、图内脚注、图注 alt、伴生台账；改其中任何一处，其余四处同步改。本班处置：正文小标题与图内标题统一为「三组读数 / 四个读数点」，图383 重画、read_image 复检，台账登记「四个读数点（分属三组读数）」与「三组读数」两行。当前性验证：改动后重跑 `python3 docs/promotion/_d89_caption_check.py` 与 `python3 docs/promotion/_d89_figcheck.py` 应得 verdict=PASS、problems=[]，并用 read_image 打开 docs/promotion/img/fig383_paper_readouts.png 确认标题与卡片排版；再 grep 正文与绘图脚本确认「三种结局」「四种结局」已不存在。"
evidence: "docs/promotion/receipts/d89-review-pkg-R1.md（G 段题3 FAIL/P2a）；docs/promotion/figures/_d89_figs.py（fig383 标题改写）；重画后 read_image 复核回执（evidence://v1/5f86101cb0ff87e33d8960ba175e8a8a1862ada84025fb03aa6c255c225c8f24）；docs/promotion/receipts/d89-caption-check.json（PASS）"
tags: [推广班, 配图, 口径一致, 审稿P2a, 计数]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-15T20:30:30.149531+08:00"
updated_at: "2026-11-15T20:30:30.149531+08:00"
---