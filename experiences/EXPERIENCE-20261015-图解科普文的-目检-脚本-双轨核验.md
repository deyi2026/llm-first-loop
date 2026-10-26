---
title: 图解科普文的「目检+脚本」双轨核验
scenario: 生成带配图的科普长文，需要确保图内数字与正文、来源三方一致，且图面无版面缺陷
root_cause: ""
solution: 1) 生成图后必须逐张 read_image 目检，重点查：卡片是否被画布下边缘切平、元素是否溢出容器边界、结构是否完整（如 F 型是否呈现两横一竖）。2) 用独立核验脚本查图数/正文数字/DOI/标题长度/AI 声明/话题标签，而不是靠肉眼。3) 目检与脚本互为补充：目检发现版面缺陷，脚本发现数字与合规缺陷。4) 修图后必须重新目检修的那几张。当前性验证：重跑 gen_images.py 后，用 `python3 outputs/<dir>/verify_figures.py` 确认输出 VERIFY_D17_ALL_PASS，且 read_image 复查刚修过的图。
evidence: outputs/lfl-article-20261015-ctr/verify_figures.py 输出 VERIFY_D17_ALL_PASS；10 张图 read_image 逐张检查并修复 3 处版面问题
tags: [配图, 科普, 核验, 数字一致性, 版面]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-15T12:21:46.336747+08:00"
updated_at: "2026-10-15T12:21:46.336747+08:00"
---

配图类科普文的核验链：generate → read_image 目检（逐张）→ 修版面 → 核验脚本跑数字一致性。三步缺一不可，其中目检发现了脚本查不出的问题（卡片被画布切平、竖条溢出容器、缺结构段），而脚本发现了目检查不出的问题（数字未成对出现、DOI 缺失、话题标签漏挂）。核验脚本的正则容易把尾随中文吞进 DOI，应用 [A-Za-z0-9._;()/-]* 而非 [^\s)\]]+。