---
title: 配图排版要双通道：read_image 视觉复核 + 像素级越界实测（本班像素抓到图 292 末框越界、视觉漏报）
scenario: LFL 推广第 67 期配图：4 张信息图（PIL 绘制 + bbox 裁剪）逐张 read_image 视觉复核，视觉模型对 fig293 报「第 1 条框内文字超出框宽」，但像素实测显示 0 越界（视觉误报）；反过来 fig292 的 G0–G4 阶梯色块里最后一个（G4）右缘 948 超出内容边界 940，视觉复核完全没报。
root_cause: ""
solution: "① 排版验收用双通道：read_image 视觉复核查文字重叠/截断/可读性，像素实测查几何越界；② 像素实测做法：PIL 打开 PNG，扫描 x > 内容右边界（如 941）且颜色偏深的像素，排除分隔线行后计数必须为 0；同时用灰度阈值求内容 bbox，确认右缘 ≤ 边界；③ 视觉报告与像素实测冲突时，以像素实测为准并把冲突记进 STATUS（如本班 fig293 视觉误报、fig292 视觉漏报）。当前性验证：跑 `python3 /tmp/lfl_d67_pixcheck2.py` 应对 4 张图各输出「text-like px beyond x=941: 0」；新增图后重跑该脚本并把新图名加进列表。"
evidence: 本班回执：read_image 对 fig293 报「第 1 条框内文件路径行超出框宽」（像素实测 0 越界，视觉误报）；像素实测在 fig292 的 y≈423 处发现 x>941 的深色像素 190 个（末框右缘 948 > 940），修正间距后 4 图均为 0；G0–G4 四个框中只有 G4 越界，其余三框在界内，故视觉漏报
tags: [配图, 排版, 像素实测, read_image]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-07T08:32:53.639846+08:00"
updated_at: "2026-11-07T08:32:53.639846+08:00"
---