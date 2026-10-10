# -*- coding: utf-8 -*-
from _draw import *

img, d = canvas("LFL 的核心循环", "llm-first-loop 定义的五个阶段：从消息进入到记忆沉淀", 470)

stages = [("消息进", "输入从 CLI / Web / 飞书\n三个通道进入"),
          ("理解", "读规则、查记忆、\n判断当前该做什么"),
          ("行动", "调用工具，程序如实\n返回执行回执"),
          ("真诚回答", "答得对，也答得诚实：\n不验证就说未验证"),
          ("记住", "写回会话记忆、\n证据与候选方法")]

bw, gap = 168, 20
x0 = (W - (bw * 5 + gap * 4)) // 2
ytop, bbh = 200, 150

for i, (t, s) in enumerate(stages):
    x = x0 + i * (bw + gap)
    d.rounded_rectangle([(x, ytop), (x + bw, ytop + bbh)], 12, fill=SOFT, outline=LINE, width=2)
    d.rounded_rectangle([(x, ytop), (x + bw, ytop + 5)], 3, fill=ACC2 if i < 4 else ACC3)
    n = str(i + 1)
    d.ellipse([(x + 14, ytop + 20), (x + 44, ytop + 50)], fill=(230, 236, 243) if i < 4 else (223, 238, 230))
    d.text((x + 29, ytop + 27), n, font=f(19), fill=ACC2 if i < 4 else ACC3, anchor="mm")
    d.text((x + bw // 2, ytop + 62), t, font=f(27), fill=INK, anchor="mm")
    for j, ln in enumerate(s.split("\n")):
        d.text((x + bw // 2, ytop + 96 + j * 26), ln, font=f(17, False), fill=MUTE, anchor="mm")
    if i < 4:
        ax = x + bw + 3
        d.polygon([(ax, ytop + 70), (ax + 14, ytop + 78), (ax, ytop + 86)], fill=(180, 188, 197))

# 回环箭头
ry = ytop + bbh + 34
d.line([(x0 + bw * 4 + gap * 4 + bw // 2 - 80, ry), (x0 + bw // 2 + 80, ry)], fill=(198, 68, 26), width=3)
d.line([(x0 + bw * 4 + gap * 4 + bw // 2 - 80, ytop + bbh), (x0 + bw * 4 + gap * 4 + bw // 2 - 80, ry)], fill=(198, 68, 26), width=3)
d.line([(x0 + bw // 2 + 80, ytop + bbh), (x0 + bw // 2 + 80, ry)], fill=(198, 68, 26), width=3)
d.polygon([(x0 + bw // 2 + 80, ytop + bbh + 6), (x0 + bw // 2 + 70, ytop + bbh - 6), (x0 + bw // 2 + 90, ytop + bbh - 6)], fill=(198, 68, 26))
lb = f(19)
tw = lb.getlength("「记住」的结果会成为下一轮「理解」的输入 —— 这就是循环")
d.text((W // 2, ry + 8), tw and "「记住」的结果成为下一轮「理解」的输入 —— 这就是循环", font=lb, fill=ACCENT, anchor="mm")

save(img, "fig1-loop.png")
