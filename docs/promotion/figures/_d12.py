# -*- coding: utf-8 -*-
"""D12: original, evidence-bounded dual-agent explainer graphics."""
from _draw import *

# fig37: independent roles, local-only decision.
img, d = canvas("双 Agent：一写一审，程序管闸", "两个角色做不同的事，第三道是确定性的 Host Gate", 708)
cards = [
    (172, ACC2, "1  Executor · 执行者",
     "独立工作区写候选；通过真实工具产生文件；冻结确切 SHA256。只认可校验的实际产物。"),
    (316, ACC3, "2  Reviewer · 独立审查者",
     "独立 Session / OS 进程，只读冻结的候选和验收条件；检查证据与风险，不能自行释放生产副作用。"),
    (460, ACCENT, "3  Host Gate · 确定性裁决",
     "重新读取 SHA / 功能测试 / STOP / 执行权与原始回执；有冲突、无证据或未知就 BLOCKED。"),
]
for y, color, title, body in cards:
    d.rounded_rectangle([52, y, W-52, y+122], radius=12, fill=(248, 249, 250), outline=color, width=3)
    d.rounded_rectangle([53, y, 63, y+122], radius=4, fill=color)
    d.text((84, y+14), title, font=f(23), fill=color)
    end=block(d, 84, y+55, body, f(18), W-178, INK, 1.5)
    assert end <= y+115, (title,end,y)
for ay in [300, 444]:
    d.line([(W//2, ay-4), (W//2, ay+6)], fill=NAVY, width=3)
    d.polygon([(W//2-7,ay+2),(W//2+7,ay+2),(W//2,ay+11)], fill=NAVY)
d.rounded_rectangle([52, 618, W-52, 661], radius=8, fill=(255,239,232))
d.text((77, 631), "离线验证通过 ≠ 生产发布许可；默认 OFF，未知状态拒收",font=f(18),fill=ACCENT)
save(img, "fig37-dual-agent-roles.png")

# fig38: real factual example.
img, d = canvas("一个符号，漏过审查却没过测试", "闭区间 [1,3] 与 [3,5]：正确结果应合并为 [1,5]", 690)
cases=[
    (55, ACC3, "正确候选", "端点相接也合并：使用 ≤", "311 / 311 通过", "Host: LOCAL_EXPERIMENT_VERIFIED"),
    (510, ACCENT, "缺陷候选", "误把 ≤ 改成 ＜", "239 / 311 通过", "72 项失败 → Host: BLOCKED"),
]
for x,c,t,cond,tests,verdict in cases:
    d.rounded_rectangle([x,180,x+435,468],radius=14,fill=(250,250,251),outline=c,width=3)
    d.text((x+20,198),t,font=f(28),fill=c)
    e=block(d,x+20,252,cond,f(22),395,INK)
    d.text((x+20,328),tests,font=f(25),fill=c)
    e2=block(d,x+20,379,verdict,f(18),395,INK,1.5)
    assert e <= 315 and e2 <= 464,(x,e,e2)
d.rounded_rectangle([62,500,W-62,562],radius=9,fill=(240,246,250),outline=ACC2,width=2)
d.text((88,509),"第一道 P1.8 结构审查：两份都得到 PASS_BOUNDED",font=f(22),fill=NAVY)
d.text((88,536),"因此 PASS_BOUNDED 并不意味着算法语义正确",font=f(18),fill=MUTE)
d.rounded_rectangle([62,590,W-62,642],radius=9,fill=(255,239,232))
d.text((88,607),"311 项是此任务的专用验收；不能外推为通用 Reviewer 准确率",font=f(18),fill=ACCENT)
save(img, "fig38-boundary-test.png")
print("FIG_D12_DONE")
