# -*- coding: utf-8 -*-
from _draw import *

# ---------- fig11: 三层状态模型 ----------
img, d = canvas("AI 的状态分三层，不是一锅粥",
                "ARCHITECTURE-ai-state-model-v1.md · 语义状态 / 上下文投影 / 执行机械", 910)
layers = [("A. Semantic AI State", "模型认知的事实源", 175, 250, ACC2,
           "Objective · Constraints · Facts · Hypotheses\nDecisions · Open Questions\nRejected Hypotheses"),
          ("B. Context Projection", "按当前请求投影出来的上下文", 480, 210, ACC3,
           "HOT 每轮可见 · WARM 摘要+引用\nCOLD 按需检索")]
for title, sub, y, h, col, body in layers:
    d.rectangle([(60, y), (W - 60, y + h)], fill=(248, 250, 252))
    d.rectangle([(60, y), (67, y + h)], fill=col)
    d.text((92, y + 18), title, font=f(27), fill=INK)
    d.text((92, y + 62), sub, font=f(18, False), fill=MUTE)
    yy = y + 100
    for ln in body.split("\n"):
        d.text((92, yy), ln, font=f(19, False), fill=INK); yy += 34
d.rectangle([(60, 750), (W - 60, 865)], fill=(248, 250, 252))
d.rectangle([(60, 750), (67, 865)], fill=MUTE)
d.text((92, 766), "C. Engine Run State", font=f(27), fill=INK)
d.text((92, 808), "stagnation · overflow · warning flags", font=f(19, False), fill=INK)
for ay, lab in [(447, "projection"), (712, "execution")]:
    d.line([(500, ay), (500, ay + 16)], fill=INK, width=3)
    d.polygon([(494, ay + 16), (506, ay + 16), (500, ay + 26)], fill=INK)
    d.text((496, ay - 4), lab, font=f(19, False), fill=INK)
save(img, "fig11-three-state-layers.png")

# ---------- fig12: 反身债务基线 ----------
img, d = canvas("把架构腐化做成一条只减不增的棘轮",
                "Kernel v1 边界契约 · 2026-10-07", 680)
d.rectangle([(60, 185), (W - 60, 350)], fill=(253, 244, 240))
d.text((92, 208), "基线：22 条反向依赖，如实登记", font=f(29), fill=(150, 50, 32))
d.text((92, 262), "core/loop→methods · runtime→methods · llm→cognitive …", font=f(19, False), fill=INK)
d.text((92, 300), "承认现实，不假装它们不存在", font=f(19, False), fill=MUTE)

d.rectangle([(60, 380), (470, 612)], fill=(238, 246, 242))
d.text((88, 404), "✓  CI 放行", font=f(26), fill=(21, 92, 60))
d.text((88, 452), "某条违规边消失了，", font=f(20, False), fill=INK)
d.text((88, 484), "且已从基线同步删除", font=f(20, False), fill=INK)
d.text((88, 532), "棘轮向下走", font=f(22), fill=(21, 92, 60))

d.rectangle([(530, 380), (W - 60, 612)], fill=(253, 240, 237))
d.text((558, 404), "✗  CI 拒绝", font=f(26), fill=(140, 45, 30))
d.text((558, 452), "出现任何未登记的", font=f(20, False), fill=INK)
d.text((558, 484), "新反向依赖边", font=f(20, False), fill=INK)
d.text((558, 532), "棘轮不许变宽", font=f(22), fill=(140, 45, 30))
save(img, "fig12-debt-ratchet.png")

# ---------- fig13: 设计意图 vs 代码现实 ----------
img, d = canvas("六个面是操作模型，不是目录结构",
                "六面归面不全，被如实记录", 600)
planes = ["Mission", "Epistemic", "Context", "Reasoning", "Action", "Evaluation"]
for i, p in enumerate(planes):
    x = 60 + i * 148
    d.rectangle([(x, 185), (x + 130, 235)], fill=ACC2)
    d.text((x + 12, 200), p, font=f(18, False), fill=(255, 255, 255))
d.text((60, 262), "—— 设计意图：六个控制面 ——", font=f(19, False), fill=MUTE)

d.line([(60, 300), (W - 60, 300)], fill=LINE, width=2)

d.rectangle([(60, 320), (W - 60, 520)], fill=(253, 240, 237))
d.text((92, 344), "—— 代码现实：26 个顶层包 + 6 能力模块，另有模块无处归面 ——", font=f(19), fill=(140, 45, 30))
for i, s in enumerate(["web/          交付面，六面里根本没有这一面",
                       "semantic_logic/  横切所有面的语义权威",
                       "session.py 109KB · history.py 97KB  天然跨面"]):
    d.text((92, 392 + i * 44), s, font=f(19, False), fill=INK)
d.text((60, 552), "差集被写进审计文档，而不是被一句「六面已落地」盖过去。",
       font=f(20, False), fill=INK)
save(img, "fig13-ideal-vs-reality.png")

# ---------- fig14: 结构有棘轮，承认的缺口没有 ----------
img, d = canvas("一个诚实的架构，和一个自省能自动执行的架构",
                "现行机械守卫覆盖情况 · 2026-10-10 核验", 620)
rows = [("22 条内核反向依赖基线", "CI 棘轮卡死", True),
        ("函数尺寸 only-decrease 基线", "CI 棘轮卡死", True),
        ("六面归面不全", "写在审计里，靠人偿还", False),
        ("持久化散在 ≥8 个 surface", "写在审计里，靠人偿还", False),
        ("方法消费率约 0.9%", "写在审计里，靠人偿还", False)]
for i, (item, guard, has) in enumerate(rows):
    y = 190 + i * 78
    col = ACC3 if has else (198, 120, 60)
    d.rectangle([(60, y), (66, y + 46)], fill=col)
    d.text((92, y + 4), item, font=f(23, False), fill=INK)
    d.text((92, y + 36), guard, font=f(18, False), fill=col)
save(img, "fig14-ratchet-coverage.png")

# ---------- fig15: 证据分持久性分级 ----------
img, d = canvas("引用还是复制？按状态的分级决定",
                "evidence_refs 耐久的存引用，易失的直接存内容", 600)
d.rectangle([(60, 180), (485, 540)], fill=(238, 246, 242))
d.text((88, 206), "Durable（跨压缩/重启要恢复）", font=f(24), fill=(21, 92, 60))
d.text((88, 258), "confirmed_facts", font=f(21), fill=INK)
d.text((88, 292), "  └ 存引用 evidence_refs", font=f(19, False), fill=MUTE)
d.text((88, 342), "decisions", font=f(21), fill=INK)
d.text((88, 376), "  └ 存引用", font=f(19, False), fill=MUTE)
d.text((88, 426), "reason：引用比复制省 token", font=f(19, False), fill=(21, 92, 60))

d.rectangle([(515, 180), (W - 60, 540)], fill=(253, 240, 237))
d.text((543, 206), "Ephemeral（只服务当前推理）", font=f(24), fill=(140, 45, 30))
d.text((543, 258), "active_hypotheses", font=f(21), fill=INK)
d.text((543, 292), "  └ 直接存内容", font=f(19, False), fill=MUTE)
d.text((543, 342), "  supporting_evidence", font=f(19, False), fill=INK)
d.text((543, 376), "  contradicting_evidence", font=f(19, False), fill=INK)
d.text((543, 426), "reason：压缩后即可丢弃", font=f(19, False), fill=(140, 45, 30))
save(img, "fig15-evidence-tiering.png")
