# -*- coding: utf-8 -*-
from _draw import *

img, d = canvas("记忆可采性：召回高，不等于这条记忆「可以用」",
                "arXiv:2610.07309 · RHELM 与 MemOps 两基准 top-20 重分析，覆盖 3767 个查询", 560)

scale, x0, barmax = 0.60, 330, 460
GRAY, BLUE = (168, 176, 186), ACC2

# 图例
lx = x0
d.rounded_rectangle([(lx, 170), (lx + 22, 188)], 4, fill=GRAY)
d.text((lx + 32, 170), "重分析前", font=f(18, False), fill=MUTE, anchor="la")
d.rounded_rectangle([(lx + 150, 170), (lx + 172, 188)], 4, fill=BLUE)
d.text((lx + 182, 170), "重分析后", font=f(18, False), fill=INK, anchor="la")

def bar(y, label, v0, v1):
    d.text((52, y + 40), label, font=f(20), fill=INK, anchor="lm")
    for j, (v, col, tc) in enumerate([(v0, GRAY, MUTE), (v1, BLUE, INK)]):
        by = y + j * 34
        bw = int(barmax * v / scale)
        d.rounded_rectangle([(x0, by), (x0 + barmax, by + 26)], 4, fill=(241, 243, 245))
        d.rounded_rectangle([(x0, by), (x0 + bw, by + 26)], 4, fill=col)
        d.text((x0 + bw + 12, by + 13), "%.3f" % v, font=f(19), fill=tc, anchor="lm")
        if j == 1:
            d.text((x0 + bw + 84, by + 13), "+%.3f" % (v1 - v0), font=f(19), fill=BLUE, anchor="lm")

bar(206, "锚点召回", 0.432, 0.533)
bar(316, "80% 召回可行性", 0.237, 0.311)

axisy = 412
d.line([(x0, axisy), (x0 + barmax, axisy)], fill=LINE, width=2)
for t in [0.0, 0.2, 0.4, 0.6]:
    xx = x0 + barmax * t / scale
    d.line([(xx, axisy), (xx, axisy + 7)], fill=(170, 178, 187), width=2)
    d.text((xx, axisy + 14), "%.1f" % t, font=f(16, False), fill=MUTE, anchor="ma")

ny = 470
d.rounded_rectangle([(52, ny), (W - 52, ny + 72)], 8, fill=(250, 252, 254), outline=(214, 224, 234), width=1)
d.text((72, ny + 16), "框架把每条「记忆-查询」组合标为三态之一：", font=f(19), fill=INK)
for i, (t, c) in enumerate([("可采信", ACC3), ("不可采信", ACCENT), ("未决", MUTE)]):
    bx = 72 + i * 210
    d.rounded_rectangle([(bx, ny + 46), (bx + 132, ny + 74)], 6, fill=c)
    d.text((bx + 66, ny + 60), t, font=f(18), fill=(255, 255, 255), anchor="mm")

save(img, "fig5-admissibility.png")
