---
title: _draw.py 信息图：canvas() 副标题占位 y≈100，图例/自绘元素须放 y≥160 且副标题≤40 字防右端截断
scenario: "用 docs/promotion/figures/_draw.py 生成信息图（canvas+block+save 流水线），需在柱状图区上方放图例或自绘元素。D27（20261021）fig111 实发：图例色块画在 y=100-126，与 canvas() 固定画在 (80,100) 的副标题重叠，视觉验收发现叠字返工；此前 fig109 副标题尾部日期右端贴边截断。"
root_cause: ""
solution: 在 _draw.py 图纸上加两条硬约束：① 图例、色块、自绘头部元素的 y 坐标必须 ≥160（canvas 分隔线在 y=142，其下才安全）；② 副标题（canvas 第二参数）长度控制在约 40 个全角字符以内，超长先截文案再重排；写图脚本时自查 getlength。D27 实测修复方式：图例移 y=164、柱区 top 由 210 降到 240 让位，read_image 复验通过。
evidence: "read_image 验收回执（2026-10-21 20:2x）：fig111 首轮报「图例色块与副标题互相遮挡叠字」，/tmp/fig111_top.png 放大核实为实锤（色块 y100-126 压 canvas 副标题 y100）；修复 _d27.py 移图例至 y164、柱区 top 240 后 /tmp/fig111_top2.png 复验「无重叠」通过。fig109 副标题尾部日期截断同日实证（缩短文案后复验通过）。"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-21T20:58:23.790048+08:00"
updated_at: "2026-10-21T20:58:23.790048+08:00"
---

docs/promotion/figures/_draw.py 的 canvas() 把副标题画在 (80,100)。自绘元素（图例色块、说明文字）若放在 y≈92-128 区间会直接压在副标题上：D27 fig111 图例色块放 y=100-126，read_image 首轮即报图例与副标题互相遮挡叠字，返工一轮（移到 y=164 即分隔线 142 之下后复验通过）。同时副标题过长会右端截断（canvas 固定 x=80 起排、无自动缩行），f(21) 字号下约 42 个全角字符以内安全。规则：图例/自绘头部元素一律放 y≥160；副标题文案控制在 40 字内或自查 font.getlength。