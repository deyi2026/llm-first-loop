---
title: 配图排版：read_image 查重叠/缺字，但公网 CDN 图不要靠小图灰度 MSE 配对
scenario: 本地 matplotlib 配图（PNG 1000×830/880/860/900）随头条图文发布后，CDN 会重新编码/裁剪，下载到的尺寸与原图不一致（实测出现 2500×1740、1080×974、956×1268、720×960 等），无法一一对应回本地图。
root_cause: MSE 配对法在结构相近的柱状图之间不可靠（实测把 fig208 误配为 fig207）；且头条 CDN 改写尺寸后像素级比较失去意义。
solution: "排版缺陷用 read_image 直接逐张看本地 PNG（重点三类：条形背景与左侧类别标签是否重叠、数值文本是否被相邻色块盖住、中文字体/希腊字母是否缺字渲染成方框），修 figures 脚本后重跑并复看；判断\"公网发的是哪一版\"不要靠图片尺寸或 64×64 灰度 MSE 配对（小尺寸灰度会把不同图错配），改用发布时实际粘贴的 HTML 文件 sha256 与工作区当前 HTML sha 对比（state log 里的 html_sha 即为发布版本），再据此登记遗留待办。"
evidence: 2026-10-31 daily47 实测：read_image 查出 fig205 左侧标签与条形背景重叠、fig206 检测率数值与右列条形重叠、fig207 副标题 ϕ 渲染缺字；64×64 灰度 MSE 把 pub07(1080×974) 判为 fig207（mse 5032）但视觉特征实为 fig208；最终以 state log html_sha 97e96b97（发布版）vs 工作区新版 aa549f0b 确定发布的是修订前版本。
tags: [配图, read_image, 排版, 图注, 公网验收]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-31T13:50:59.550439+08:00"
updated_at: "2026-10-31T13:50:59.550439+08:00"
---