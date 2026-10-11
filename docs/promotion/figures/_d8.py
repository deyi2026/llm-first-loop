# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _draw import *

# ---------------- fig28: 四种结局 ----------------
img, d = canvas("一次自动化调度的四种结局", "从左到右，可核对性依次增强；只有最右侧才算真正完成", 470)
boxes = [
    ("通知已发", "到点显示了一行字", "证明提醒机制活着\n不证明任务被执行", ACC2, 0),
    ("续跑已启动", "执行被拉起来了", "启动 ≠ 跑完\n进程可能刚起就崩", ACC2, 1),
    ("续跑已结算", "跑完且有终态", "终态还分完成/放弃/\n截断/拒绝，不能算成功", ACC3, 2),
    ("已被核对", "有人真去看了一眼产出物", "只有这一栏对应\n你最初想要的结果", ACCENT, 3),
]
bw, gap, x0, y0 = 212, 24, 52, 190
for i, (t, s1, s2, col, lv) in enumerate(boxes):
    x = x0 + i * (bw + gap)
    d.rounded_rectangle([x, y0, x + bw, y0 + 210], 12, fill=SOFT, outline=col, width=2)
    d.rectangle([x, y0, x + bw, y0 + 46], fill=col)
    d.text((x + 16, y0 + 12), t, font=f(23), fill=(255, 255, 255))
    yy = block(d, x + 16, y0 + 62, s1, f(17), bw - 32, INK, 1.5)
    d.line([(x + 16, yy + 8), (x + bw - 16, yy + 8)], fill=LINE, width=1)
    block(d, x + 16, yy + 20, s2, f(15), bw - 32, MUTE, 1.5)
    if i < 3:
        ax = x + bw + 4
        d.line([(ax, y0 + 105), (ax + 16, y0 + 105)], fill=(170, 178, 188), width=3)
        d.polygon([(ax + 16, y0 + 105), (ax + 6, y0 + 99), (ax + 6, y0 + 111)], fill=(170, 178, 188))
# 底部提示
d.rounded_rectangle([52, 424, W - 52, 460], 8, fill=(253, 243, 238))
d.text((72, 433), "常见误判：在第一栏就认为任务完成 —— 越往后，可核对的证据越多", font=f(17), fill=ACCENT)
save(img, "fig28-four-outcomes.png")

# ---------------- fig29: 授权链路 ----------------
img, d = canvas("自动续跑的授权链路", "每一段都有人类在场；断掉任何一段，链路就不成立", 430)
steps = [
    ("真人本轮输入", "真人在会话里敲的话"),
    ("同会话授权", "不能跨会话转手"),
    ("一次性委派", "降权，不是新授权"),
]
bw2, gp = 200, 32
y1 = 185
for i, (t, s) in enumerate(steps):
    x = 52 + i * (bw2 + gp)
    d.rounded_rectangle([x, y1, x + bw2, y1 + 104], 10, fill=(255, 255, 255), outline=NAVY, width=2)
    d.text((x + 18, y1 + 20), t, font=f(22), fill=NAVY)
    block(d, x + 18, y1 + 58, s, f(16), bw2 - 36, MUTE, 1.5)
    if i < 2:
        ax = x + bw2 + 8
        d.line([(ax, y1 + 52), (ax + 40, y1 + 52)], fill=NAVY, width=3)
        d.polygon([(ax + 40, y1 + 52), (ax + 28, y1 + 45), (ax + 28, y1 + 59)], fill=NAVY)
# 终点
ex = 52 + 3 * (bw2 + gp)
d.rounded_rectangle([ex, y1, ex + bw2, y1 + 104], 10, fill=(255, 240, 236), outline=ACCENT, width=2)
d.text((ex + 18, y1 + 20), "执行一次", font=f(22), fill=ACCENT)
d.text((ex + 18, y1 + 58), "然后停下", font=f(16), fill=MUTE)
ax2 = 52 + 2 * (bw2 + gp) + bw2 + 8
d.line([(ax2, y1 + 52), (ex - 6, y1 + 52)], fill=NAVY, width=3)
d.polygon([(ex - 6, y1 + 52), (ex - 18, y1 + 45), (ex - 18, y1 + 59)], fill=NAVY)
# 两条禁止
d.rounded_rectangle([52, 330, 486, 404], 10, fill=SOFT, outline=LINE, width=2)
d.text((72, 344), "两条硬性禁止", font=f(20), fill=INK)
d.text((72, 376), "① 不可周期：周期任务只发通知，是否继续由真人决定", font=f(17), fill=ACCENT)
d.rounded_rectangle([514, 330, W - 52, 404], 10, fill=SOFT, outline=LINE, width=2)
d.text((534, 344), "后台与子代理无权申请", font=f(20), fill=INK)
d.text((534, 376), "分身不能给自己续命，必须等父任务来取结果", font=f(17), fill=ACCENT)
save(img, "fig29-authorization-chain.png")

# ---------------- fig30: 失败判定 ----------------
img, d = canvas("授权失效：退避重试 vs 确定性终态", "关键不是失败了多重，而是它会不会自己好", 470)
# 左：瞬态
d.rounded_rectangle([52, 185, 486, 330], 12, fill=(255, 255, 255), outline=ACC3, width=2)
d.rectangle([52, 185, 486, 229], fill=ACC3)
d.text((72, 196), "瞬态失败 —— 会自愈", font=f(23), fill=(255, 255, 255))
block(d, 72, 248, "例：网络抖动、进程短暂不可用", f(18), 390, INK)
block(d, 72, 286, "处置：有界退避重试，多半能自己恢复", f(18), 390, ACC3)
# 右：确定性终态
d.rounded_rectangle([514, 185, W - 52, 330], 12, fill=(255, 255, 255), outline=ACCENT, width=2)
d.rectangle([514, 185, W - 52, 229], fill=ACCENT)
d.text((534, 196), "确定性终态 —— 不会自愈", font=f(23), fill=(255, 255, 255))
block(d, 534, 248, "例：一次性授权已丢失，支撑凭据不存在", f(18), 390, INK)
block(d, 534, 286, "实测：6 次退避约 30 分钟，无一自愈", f(18), 390, ACCENT)
# 分岔标签
d.line([(500, 185), (500, 160), (269, 160)], fill=LINE, width=2)
d.line([(500, 185), (500, 160), (731, 160)], fill=LINE, width=2)
d.text((452, 138), "这次失败了，能修好吗？", font=f(17), fill=MUTE)
# 底部处置
d.rounded_rectangle([52, 356, W - 52, 440], 10, fill=SOFT, outline=LINE, width=2)
d.text((74, 370), "判定为终态后要做两件事", font=f(20), fill=INK)
d.text((74, 402), "① 立刻降级为普通通知发出去  ② 附上重新授权所需的信息，让人能补一次", font=f(18), fill=INK)
save(img, "fig30-terminal-vs-transient.png")
