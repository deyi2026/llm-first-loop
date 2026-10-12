# -*- coding: utf-8 -*-
from _draw import *

img, d = canvas("MCP 规则注入实验：两个基准的结果", "arXiv:2610.10659 · DualGauge 59 个 Python 任务 / BaxBench 28 个后端场景", 620)

groups = [
    ("DualGauge 全部安全测试通过", 44.1, 78.0),
    ("BaxBench 功能正确解中无成功攻击", 65.0, 86.0),
]
base_x, bar_max = 390, 360

for gi, (gname, p0, p1) in enumerate(groups):
    gy = 186 + gi * 168
    d.text((52, gy), gname, font=f(21), fill=INK)
    delta = p1 - p0
    d.text((W - 52, gy), "+%.1f 个百分点" % delta, font=f(21), fill=ACC2, anchor="ra")
    for bi, (bl, v, col) in enumerate([("基线", p0, (176, 184, 193)), ("MCP 注入后", p1, ACC2)]):
        by = gy + 34 + bi * 48
        d.text((52, by + 18), bl, font=f(18, False), fill=MUTE, anchor="lm")
        bw = int(bar_max * v / 100)
        d.rounded_rectangle([(base_x, by), (base_x + bar_max, by + 36)], 5, fill=(241, 243, 245))
        d.rounded_rectangle([(base_x, by), (base_x + bw, by + 36)], 5, fill=col)
        d.text((base_x + bw + 14, by + 18), "%.1f%%" % v, font=f(21), fill=INK, anchor="lm")

ny = 540
d.rounded_rectangle([(52, ny), (W - 52, ny + 48)], 8, fill=(253, 246, 243))
d.text((W // 2, ny + 24), "论文自述局限：全部实验仅用 1 个模型、每任务仅生成 1 次 —— 单点实验，非定论",
       font=f(18), fill=(150, 60, 26), anchor="mm")

save(img, "fig4-mcp.png")
