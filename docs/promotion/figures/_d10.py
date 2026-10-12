# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _draw import *

# ---------- fig33: 心跳协议 ----------
img, d = canvas("什么动作算活着？", "纯文本回复 = 立即结算；带工具调用 = 存活", 520)
# 上：死
d.rounded_rectangle([52, 176, W-52, 316], 12, fill=(255,251,250), outline=ACCENT, width=2)
d.rectangle([52, 176, W-52, 222], fill=ACCENT)
d.text((72, 188), "纯文本回复 → 运行时立即结算", font=f(22), fill=(255,255,255))
d.text((W-260, 190), "实测 child#1", font=f(16), fill=(255,225,218))
block(d, 72, 238, "「进入等待循环，不再调用工具。」——这句话发出后没有任何工具调用，运行时当轮结算下线：3 轮 / 5 次工具 / 56,405 input tokens。",
      f(17), 400, INK)
# 下：活
d.rounded_rectangle([52, 336, W-52, 476], 12, fill=(250,253,250), outline=ACC3, width=2)
d.rectangle([52, 336, W-52, 382], fill=ACC3)
d.text((72, 348), "每轮携带一次只读工具调用（心跳）", font=f(22), fill=(255,255,255))
block(d, 72, 398, "心跳 = 查 1 条会话事件，最便宜的只读调用；每轮必带，直到父代理发 [ROOM-END] 才允许输出纯文本总结并结算。实测：18 次心跳 / 2.5 分钟 / 双注入完整送达。",
      f(17), 400, INK)
d.text((52, 138), "对模型说「别死」没用，要写清「怎样算活着」", font=f(20), fill=NAVY)
save(img, "fig33-heartbeat.png")

# ---------- fig34: 成本对比 ----------
img, d = canvas("两种房间形态，两张账单", "空闲等待在 token 经济里按分钟计费", 596)
# 左柱：Mode-L
LX = 120
def bar(x, label, sub, h, col, vtxt):
    base = 470
    d.rounded_rectangle([x, base-h, x+150, base], 10, fill=col)
    d.text((x+75-len(vtxt)*8, base-h-30), vtxt, font=f(19), fill=INK)
    d.text((x+12, base+10), label, font=f(19), fill=INK)
    d.text((x+8, base+38), sub, font=f(15), fill=MUTE)
d.line([70, 470, W-70, 470], fill=LINE, width=2)
bar(130, "长驻心跳房", "空闲 6.4–9.6万/分钟/个", 210, ACCENT, "150–200万")
bar(400, "每轮重开房", "空闲成本 0", 62, ACC3, "40–50万")
d.text((60, 130), "3 个 Bot × 3 轮，input token 总量（设计估算）", font=f(20), fill=INK)
block(d, 60, 168, "初版设计粗估 30 万——把「每轮全上下文重放 15.6–18.8K × 轮转 10–15 秒」乘进去后，实际是 150–200 万，低估 5–7 倍。",
      f(17), 480, MUTE)
d.rounded_rectangle([60, 534, W-60, 576], 8, fill=(236,244,255))
d.text((80, 545), "主验证实测（每轮重开）：7 次拉起 / 27 分钟 / 158,350 in", font=f(17), fill=NAVY)
save(img, "fig34-room-cost.png")
print("done")
