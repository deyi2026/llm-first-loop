# -*- coding: utf-8 -*-
from _draw import *

def ctext(d, x, y, s, font, fill=INK):
    """按画布右边界居中绘制单行文本"""
    w = font.getlength(s)
    d.text((x - w / 2, y), s, font=font, fill=fill)

# ---------- fig6: 一致 != 正确 ----------
img, d = canvas("稳定的裁判，未必是对的裁判",
                "arXiv:2610.12083 · 6 个模型中最「确定」的一根", 660)
d.text((110, 176), "最「确定」的那根裁判，同样两项指标：", font=f(23), fill=INK)
vals = [("判定一致率", 100, ACC2), ("与标准答案\n吻合率", 51, ACCENT)]
base = 490
for j, (lab, val, col) in enumerate(vals):
    cx = 110 + j * 230
    hgt = int(val * 1.8)
    top = base - hgt
    d.rectangle([(cx, top), (cx + 150, base)], fill=col)
    d.text((cx + 30, top - 56), f"{val}%", font=f(40), fill=col)
    yy = base + 16
    for ln in lab.split("\n"):
        d.text((cx + 46, yy), ln, font=f(19, False), fill=MUTE); yy += 32
d.line([(70, base), (930, base)], fill=LINE, width=2)
d.line([(80, 578), (W - 80, 578)], fill=LINE, width=2)
d.text((80, 596), "它的满分一致率，来自一遍遍重复同一个「错」——错得非常稳定。",
       font=f(19, False), fill=INK)
save(img, "fig6-consistency-vs-correctness.png")

# ---------- fig7: 三种自证陷阱 ----------
img, d = canvas("「自证陷阱」的三种形态", "让 AI 自己给自己打分，会发生什么", 640)
cards = [
    ("① 当场自批", "刚蒸馏出的经验，\n在同一次会话里自我\n评价、自我批准、\n直接生效。",
     "程序拦截", "candidate 不得直接转 active", ACCENT),
    ("② 换域伪装", "只在一个任务域验证过，\n却声称这是「通用经验」。",
     "程序拦截", "激活需 ≥2 个不同 task_type", ACC2),
    ("③ 合理即通过", "输出「看起来合理」\n就算通过，标准锚在\n流畅度而非事实。",
     "程序拦不住", "只能要求 AI 标注 unverified", ACC3),
]
for i, (t, body, gl, guard, col) in enumerate(cards):
    x = 60 + i * 300
    d.rectangle([(x, 180), (x + 264, 570)], fill=SOFT)
    d.rectangle([(x, 180), (x + 264, 186)], fill=col)
    d.text((x + 22, 206), t, font=f(25), fill=INK)
    y = 258
    for ln in body.split("\n"):
        d.text((x + 22, y), ln, font=f(17, False), fill=INK); y += 33
    d.line([(x + 22, 400), (x + 242, 400)], fill=LINE, width=2)
    d.text((x + 22, 424), gl, font=f(18), fill=col)
    d.text((x + 22, 462), guard, font=f(16, False), fill=MUTE)
save(img, "fig7-self-attestation-traps.png")

# ---------- fig8: 四道门 ----------
img, d = canvas("LFL 用四道程序门，把「自我批准」拆开",
                "src/llm_loop/methods/store.py", 700)
stages = [("candidate", "蒸馏产出", 150, MUTE),
          ("qualified", "有带来源的通过记录", 500, ACC2),
          ("active", "跨 ≥2 个任务域通过", 850, ACC3)]
for i, (name, note, cx, col) in enumerate(stages):
    d.rectangle([(cx - 105, 186), (cx + 105, 288)], fill=col)
    ctext(d, cx, 208, name, f(26, False), (255, 255, 255))
    ctext(d, cx, 250, note, f(15, False), (238, 242, 246))
    if i < 2:
        d.line([(cx + 107, 237), (cx + 165, 237)], fill=INK, width=3)
        d.polygon([(cx + 165, 231), (cx + 181, 237), (cx + 165, 243)], fill=INK)

d.line([(60, 330), (W - 60, 330)], fill=LINE, width=2)
gates = [
    ("第 1 门", "candidate 不得直接转 active——同一次会话的自蒸馏不能一步生效。", ACCENT),
    ("第 2 门", "qualified 需至少一条 promotion=pass、且带运行期 episode 来源的资格记录。", ACCENT),
    ("第 3 门", "active 需 verdict=pass 的记录覆盖 ≥2 个不同 task_type；unknown 不计数，存量卡不回溯。", ACCENT),
    ("第 4 门", "作废与退役需独立事实依据：一次 verdict=fail，或 ≥2 个不同 episode 的拒绝使用声明。", ACC2),
]
for i, (t, s, col) in enumerate(gates):
    y = 352 + i * 78
    d.rectangle([(60, y), (60 + 76, y + 30)], fill=col)
    ctext(d, 98, y + 6, t, f(19), (255, 255, 255))
    d.text((154, y + 3), s, font=f(18, False), fill=INK)
d.text((60, 664), "reopen 永久可用：程序不删东西，也不替 AI 判断一条经验该不该死。",
       font=f(18, False), fill=MUTE)
save(img, "fig8-four-program-gates.png")

# ---------- fig9: 弱模型 A/B ----------
img, d = canvas("上线前的一次弱模型对照",
                "EVO-20261010-994e30f4 · qwen3.8-flash-next · temp=0 · 3 reps", 760)
d.text((60, 170), "三轮结果（两臂对称比较只在 G2 出现不对称）", font=f(24), fill=INK)
rows = [
    ("G1  身份轮",     "3/3", "3/3", "两臂工具集合完全一致", ACC3),
    ("G2  域已知任务轮", "0/3", "3/3", "A 臂输出全空，见下方说明", (150, 30, 20)),
    ("G3  域未指明轮",  "3/3", "3/3", "两臂均正常，B 臂省略 task_type", ACC3),
]
d.text((300, 226), "ARM-A", font=f(20), fill=MUTE)
d.text((470, 226), "ARM-B", font=f(20), fill=MUTE)
for i, (name, a, b, note, col) in enumerate(rows):
    y = 266 + i * 62
    if col == ACCENT:
        d.rectangle([(56, y - 6), (944, y + 44)], fill=(250, 233, 228))
    d.text((66, y), name, font=f(21), fill=INK)
    d.text((300, y), a, font=f(24), fill=(150, 30, 20) if a == "0/3" else MUTE)
    d.text((470, y), b, font=f(24), fill=col)
    d.text((580, y + 4), note, font=f(17, False), fill=MUTE)
d.line([(70, 466), (W - 70, 466)], fill=LINE, width=2)
d.text((80, 486), "如实声明：G2 中 A 臂空输出源于 2000 token 预算被 thinking 耗尽，属模型×预算交互，",
       font=f(18, False), fill=INK)
d.text((80, 518), "不是新参数导致。故该轮「两臂对称比较」不可得——只能说 B 臂可用且无劣化，n=3。",
       font=f(18, False), fill=INK)
d.text((80, 566), "另：首轮 max_tokens=500 时两臂大面积空输出，判为测试装置功率不足，",
       font=f(18, False), fill=INK)
d.text((80, 598), "提至 2000 重跑，首轮 JSON 留档但明确不作为通过证据。",
       font=f(18, False), fill=INK)
d.line([(70, 646), (W - 70, 646)], fill=LINE, width=2)
d.text((80, 664), "全量单测 7354 passed / 108 skipped / 0 failed。", font=f(18, False), fill=MUTE)
save(img, "fig10-weak-model-ab.png")

# ---------- fig10: 程序能守 / 守不住 ----------
img, d = canvas("程序守得住什么，守不住什么", "LFL 的设计边界：只卡结构，不裁判内容", 600)
d.rectangle([(60, 180), (485, 540)], fill=(238, 246, 242))
d.text((88, 206), "程序能核验（可硬拦）", font=f(26), fill=(21, 92, 60))
for i, s in enumerate(["状态迁移是否合法", "通过记录的条数与去重计数",
                       "是否带运行期 episode 来源", "存量卡是否被回溯追改",
                       "文件是否存在、内容是否完整"]):
    y = 268 + i * 52
    d.ellipse([(90, y + 8), (108, y + 26)], fill=ACC3)
    d.text((122, y), s, font=f(19, False), fill=INK)
d.rectangle([(515, 180), (940, 540)], fill=(253, 240, 237))
d.text((543, 206), "程序核验不了（只能如实标注）", font=f(26), fill=(140, 45, 30))
for i, s in enumerate(["task_type 声明的是不是真话", "经验内容本身对不对",
                       "语义是否真的跨了域", "「通过」判定是否名副其实",
                       "AI 是否在有意伪造"]):
    y = 268 + i * 52
    d.ellipse([(545, y + 8), (563, y + 26)], fill=ACCENT)
    d.text((577, y), s, font=f(19, False), fill=INK)
d.text((60, 562), "颜色仅为分类标识，不代表「安全/不安全」的等级。", font=f(17, False), fill=MUTE)
save(img, "fig9-program-boundary.png")
