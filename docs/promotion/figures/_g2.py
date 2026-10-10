# -*- coding: utf-8 -*-
from _draw import *

img, d = canvas("程序与模型的分工", "LFL 的核心主张：判断交还模型，六类硬边界程序不让", 640)

LW, RW = 424, 424
lx, rx, ty, bh = 52, W - 52 - RW, 176, 400

d.rounded_rectangle([(lx, ty), (lx + LW, ty + bh)], 12, fill=(250, 252, 254), outline=(205, 219, 233), width=2)
d.rounded_rectangle([(rx, ty), (rx + RW, ty + bh)], 12, fill=(254, 250, 248), outline=(236, 210, 198), width=2)

d.text((lx + LW // 2, ty + 30), "交给大模型判断", font=f(26), fill=ACC2, anchor="mm")
d.text((rx + RW // 2, ty + 30), "程序死守，不让", font=f(26), fill=ACCENT, anchor="mm")

left = ["该不该做、做到什么程度 —— 交给模型", "方案好坏判断与自我修正", "压缩上下文还是就此收尾", "演进建议的提出与复核结论", "失败后的恢复策略选择"]
right = ["真实执行 / 持久化", "协议与授权边界", "灾难性安全硬阻断", "物理资源约束", "崩溃恢复", "不可重复副作用边界"]

y = ty + 72
for s in left:
    d.ellipse([(lx + 30, y + 7), (lx + 42, y + 19)], fill=ACC2)
    y = block(d, lx + 58, y, s, f(19, False), LW - 90, lh=1.5) + 16

y = ty + 72
for i, s in enumerate(right):
    d.rounded_rectangle([(rx + 28, y + 1), (rx + 44, y + 19)], 3, fill=ACCENT)
    d.text((rx + 36, y + 10), str(i + 1), font=f(13), fill=(255, 255, 255), anchor="mm")
    d.text((rx + 58, y), s, font=f(19), fill=INK)
    y += 44

d.line([(W // 2, ty - 12), (W // 2, ty + bh + 12)], fill=LINE, width=2)

ny = ty + bh + 26
d.rounded_rectangle([(52, ny), (W - 52, ny + 44)], 8, fill=(253, 246, 243))
d.text((W // 2, ny + 22), "程序不代模型下「已验证通过」的结论 —— 验证结果如实标注 unverified",
       font=f(19), fill=(150, 60, 26), anchor="mm")

save(img, "fig2-division.png")
