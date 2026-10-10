# -*- coding: utf-8 -*-
from _draw import *

img, d = canvas("近两周 arXiv 上发生了什么", "本文引用的 6 篇论文，集中在同一条主线：Agent 记忆与自我演进", 610)

rows = [
    ("10/05", "记忆可采性验证", "2610.07309", "召回率高 ≠ 路由合规；给「记忆-查询」打可采信/不可采信/未决三态", ACC2),
    ("10/07", "MCP 安全规则注入", "2610.10659", "通过 MCP 在生成时交付治理过的安全需求，安全通过率显著上升", ACCENT),
    ("10/08", "Embodied Turing Machines", "2610.12369", "把决策完全写成代码，大模型不进决策回路，状态显式可存", ACC3),
    ("10/08", "认知谦逊评估", "2610.12360", "检索证据与先验信念冲突时，Agent 会不会承认不知道", ACC2),
    ("10/08", "上下文中的奖励学习？", "2610.11152", "反思「上下文强化学习」这个说法本身是否成立", MUTE),
]

ty, rh = 186, 80
for i, (dt, title, aid, desc, col) in enumerate(rows):
    y = ty + i * rh
    d.rounded_rectangle([(52, y), (W - 52, y + 68)], 8, fill=(250, 251, 252), outline=LINE, width=1)
    d.rectangle([(52, y), (58, y + 68)], fill=col)
    d.text((78, y + 34), dt, font=f(21), fill=MUTE, anchor="lm")
    d.text((150, y + 34), title, font=f(23), fill=INK, anchor="lm")
    tw = d.textlength(title, font=f(23))
    d.text((150 + tw + 14, y + 35), "arXiv:" + aid, font=f(17, False), fill=col, anchor="lm")
    d.text((78, y + 55), desc, font=f(17, False), fill=MUTE, anchor="lm")

save(img, "fig3-papers.png")
