---
title: 绘图脚本的函数名、顶部注释块标题、产出文件名三者必须一致——改图后交叉写错会让图与图注张冠李戴
scenario: LFL 推广班次的自绘信息图流水线：一个绘图脚本里用多个 def figNNN() 生成多张图，每张图在 caption check 回执里按「面板名 → 图片文件」做映射核对。d78（2026-11-11 晚班）在批量改图时把 fig333 与 fig334 的函数体交叉写错了位置（函数名、顶部注释块标题、save_crop 产出的文件名三者互相错位），机检因此报「figure333 配到了 fig334 的图」并把 fig333 判为缺失。若当时没看这一条，图与图注就会张冠李戴地发布出去。
root_cause: ""
solution: "规则：绘图脚本里「函数名 / 顶部注释块标题 / save_crop 产出的文件名」三者必须一致，且 caption check 的面板映射表要与产出文件名逐张对齐。做法：每个 figNNN() 的注释块标题用「# ==== figNNN ====」这类显式锚点包起来，改图后逐个核对函数名与产出名；跑 caption check，若某面板报 missing 或 img_size 与 manifest 不符，先怀疑映射写错而不是图没生成。当前性验证：跑 `python3 docs/promotion/figures/_d78.py` 后 `python3 docs/promotion/_d78_caption_check.py` 应输出 CAPTION CHECK PASS 且 4 张面板 ok: True；并 `grep -n \"def fig33\" docs/promotion/figures/_d78.py` 看函数名与 save_crop 的文件名是否同一数字。"
evidence: docs/promotion/receipts/d78-caption-check.json（figure331–334 面板与 img 映射错，fig333 误配 fig334 的 img）与 docs/promotion/figures/_d78.py（def fig333/fig334 与文件产出名不一致）；订正后重跑 caption check 得 CAPTION CHECK PASS
tags: [LFL推广, 配图, 机检, 映射错位]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-11T20:31:40.728699+08:00"
updated_at: "2026-11-11T20:31:40.728699+08:00"
---