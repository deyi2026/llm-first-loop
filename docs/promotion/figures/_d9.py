# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _draw import *

# ---------- fig31: 16 个门禁的两种命运 ----------
img, d = canvas("16 个门禁点的两种命运", "不是所有卡点都允许你举证；6 个是硬拒", 500)
# 左：可举证推进
d.rounded_rectangle([52, 186, 500, 404], 12, fill=(255,255,255), outline=ACC3, width=2)
d.rectangle([52, 186, 500, 232], fill=ACC3)
d.text((72, 198), "10 个 · 一致性门禁", font=f(24), fill=(255,255,255))
d.text((390, 200), "可举证推进", font=f(17), fill=(255,255,255))
block(d, 72, 250, "卡住的原因是「忙」「缺产物」这类可被修复的状态，模型可以提交证据推动它往前走。",
      f(17), 404, INK)
block(d, 72, 300, "例：waiting_for_idle、precheck:artifact、verify",
      f(17), 404, MUTE)
d.rounded_rectangle([72, 356, 480, 388], 8, fill=(236,244,255))
d.text((90, 364), "举证推进 ≠ 一定通过，仍要程序裁决", font=f(17), fill=NAVY)
# 右：不可穿透
d.rounded_rectangle([524, 186, W-52, 404], 12, fill=(255,255,255), outline=ACCENT, width=2)
d.rectangle([524, 186, W-52, 232], fill=ACCENT)
d.text((544, 198), "6 个 · 硬拒", font=f(24), fill=(255,255,255))
d.text((812, 200), "不可 override", font=f(17), fill=(255,255,255))
block(d, 544, 250, "物理不可能 4 个：port_in_use、process_mutex、stop_failure、mirror_isolation",
      f(17), 380, INK)
block(d, 544, 304, "身份冲突 2 个：precheck:service_binding、precheck:dual_root_identity",
      f(17), 380, INK)
d.rounded_rectangle([544, 356, W-72, 388], 8, fill=(255,240,236))
d.text((562, 364), "命中即返回明确拒绝理由，不静默", font=f(17), fill=ACCENT)
# 分岔标题
d.text((50, 150), "这件事，是证据不够，还是你根本没资格说？", font=f(20), fill=INK)
save(img, "fig31-gate-tiers.png")

# ---------- fig32: 证据强度 × 可协商性 ----------
img, d = canvas("验收是二维的，不是线性打分", "两条轴正交，一条轴替代不了另一条", 520)
LX, LY, CW, CH = 200, 196, 300, 150
# 四个象限
cells = [
    (0, 0, "E1 机械事实", "可谈", "查得到，也能修", "例：产物缺失\n→ 举证推进", ACC3),
    (1, 0, "E1 机械事实", "不可谈", "查得到，但没资格谈", "例：端口被占\n→ 你说了不算", ACCENT),
    (0, 1, "E3 纯声明", "可谈", "你说了算，但没人查", "「我觉得没问题」\n→ 谁都无法复核", MUTE),
    (1, 1, "E3 纯声明", "不可谈", "一句话就想越权", "最危险的一格\n→ 直接驳回", ACCENT),
]
for cx, cy, ev, ng, t1, t2, col in cells:
    x = LX + cx * CW
    y = LY + cy * CH
    d.rectangle([x, y, x + CW, y + CH], fill=(255,255,255), outline=LINE, width=1)
    d.rectangle([x, y, x + 5, y + CH], fill=col)
    d.text((x + 20, y + 16), f"{ev} · {ng}", font=f(19), fill=col)
    block(d, x + 20, y + 54, t1, f(17), CW - 44, INK)
    block(d, x + 20, y + 92, t2, f(16), CW - 44, MUTE)
# 轴标签
d.text((LX + 8, LY - 32), "← 有得谈（可举证推进）", font=f(18), fill=INK)
d.text((LX + CW + 8, LY - 32), "没得谈（不可穿透）→", font=f(18), fill=ACCENT)
d.text((56, LY + 56), "说法有多硬", font=f(19), fill=INK)
d.text((56, LY + 92), "E1 机械事实", font=f(16), fill=ACC3)
d.text((56, LY + CH + 56), "E3 纯声明", font=f(16), fill=MUTE)
# 底部
d.rounded_rectangle([LX, 520, W-52, 566], 8, fill=SOFT, outline=LINE, width=2)
d.text((LX + 20, 532), "一句话有多硬 ≠ 你有没有资格说 —— 两条轴不能互相替代", font=f(19), fill=INK)
save(img, "fig32-evidence-vs-negotiable.png")
