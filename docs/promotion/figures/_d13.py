# -*- coding: utf-8 -*-
"""D13: original, evidence-bounded heartbeat-protocol explainer graphics."""
from _draw import *

# fig39: the survival rule — plain text ends the round.
img, d = canvas("存活规则：这一轮有没有工具调用", "纯文本结束一轮 = 立即结算；父代理再发消息 = 确定性拒绝", 690)
cases = [
    (55, ACC3, "纯文本结束（原方案）",
     "「好的，我在等你的指令」", "rounds=3 / tools=5", "运行时立即结算 completed", "56,405 in / 5,930 out"),
    (510, ACCENT, "工具调用结束（心跳）",
     "每轮读一次只读事件流并回传", "8 轮全程 running", "直到主动宣布房间结束才结算", "140,891 in / 4,339 out"),
]
for x, c, t, cond, rounds, verdict, toks in cases:
    d.rounded_rectangle([x, 172, x + 435, 470], radius=14, fill=(250, 250, 251), outline=c, width=3)
    d.text((x + 20, 190), t, font=f(27), fill=c)
    e = block(d, x + 20, 240, cond, f(21), 392, INK)
    assert e <= 300, (t, e)
    d.text((x + 20, 306), rounds, font=f(24), fill=c)
    e2 = block(d, x + 20, 348, verdict, f(20), 392, INK, 1.5)
    assert e2 <= 396, (t, e2)
    d.text((x + 20, 414), toks, font=f(19), fill=MUTE)
d.rounded_rectangle([62, 502, W - 62, 566], radius=9, fill=(240, 246, 250), outline=ACC2, width=2)
d.text((88, 516), "两个 bot 做的是同一件事，结局完全不同", font=f(23), fill=NAVY)
d.text((88, 542), "差别只在一条指令怎么写", font=f(19), fill=MUTE)
d.rounded_rectangle([62, 594, W - 62, 656], radius=9, fill=(255, 239, 232))
d.text((88, 611), "同环境实测（llm-first-loop，2026-10-11 V2a POC）；", font=f(19), fill=ACCENT)
d.text((88, 634), "数值不可外推为通用基准", font=f(19), fill=ACCENT)
save(img, "fig39-heartbeat-protocol.png")

# fig40: the cost line — when to use it, when not to.
img, d = canvas("心跳协议的价码与适用边界", "每轮心跳 ≈ 全上下文重放；每分钟空转 ≈ 13 万 input tokens", 672)
rows = [
    (168, ACC3, "值得用心跳房", "人工观察窗口、外部事件等待、跨指令间隙保持可寻址", "实测：18 次心跳 + 双注入，2.5min 收尾，出口正常"),
    (322, ACCENT, "不值得用心跳房", "任务型协作：每轮有实质产出才轮换（回合制）", "单轮 0.5–1.5min（轻）～8.5min（重）；塞心跳房 = 每分钟白付 13 万"),
    (476, NAVY, "不要依赖的设计", "把「机器人能随时被叫回来」当作架构前提", "结算后发消息 = 确定性拒绝；续命手段 followup 有硬配额"),
]
for y, c, t, cond, note in rows:
    d.rounded_rectangle([52, y, W - 52, y + 124], radius=12, fill=(248, 249, 250), outline=c, width=3)
    d.rounded_rectangle([53, y, 63, y + 124], radius=4, fill=c)
    d.text((84, y + 14), t, font=f(25), fill=c)
    e = block(d, 84, y + 54, cond, f(19), W - 178, INK, 1.5)
    assert e <= y + 86, (t, e)
    e2 = block(d, 84, y + 90, note, f(18), W - 178, MUTE, 1.5)
    assert e2 <= y + 118, (t, e2)
d.rounded_rectangle([52, 624, W - 52, 652], radius=8, fill=(255, 239, 232))
d.text((77, 629), "成本口径：心跳每轮约 17.6K input；#5 房 2.5min / 323K = 约 130K in/min", font=f(18), fill=ACCENT)
save(img, "fig40-heartbeat-cost.png")
print("FIG_D13_DONE")
