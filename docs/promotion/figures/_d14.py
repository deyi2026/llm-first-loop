# -*- coding: utf-8 -*-
"""D14: LFL power-split + self-evolution locks."""
from _draw import *

img, d = canvas("分权：哪些判断程序绝不接手", "左侧 = 模型做不到或不可靠；右侧 = 归模型，程序不许写那一行 if", 700)
left = [
    ("真实执行与持久化", "模型没法自己保证 tool_call_id 不丢"),
    ("协议完整性", "绑定关系错了，后面全错"),
    ("灾难性安全硬阻断", "高危破坏类命令，且不可被审批放行"),
    ("物理资源与崩溃恢复", "进程死了，得有人把它拉起来"),
]
right = [
    ("理解、取舍、策略", "语义判断，程序的确定性是天花板"),
    ("完成裁决", "「做完了没有」归模型，最诱人也最忍不住"),
    ("证据适用性", "程序只报新鲜度；「现在还作数吗」是语义"),
    ("模型切换决策", "用哪个模型，由模型自己判断"),
]
d.text((62, 160), "归程序（不可让渡）", font=f(27), fill=NAVY)
d.text((530, 160), "归模型 + 文档规则", font=f(27), fill=ACCENT)
y = 206
for a, b in left:
    d.rounded_rectangle([52, y, 468, y + 96], radius=12, fill=(240, 246, 250), outline=ACC2, width=2)
    d.text((72, y + 12), a, font=f(23), fill=NAVY)
    e = block(d, 72, y + 48, b, f(19), 380, MUTE, 1.5)
    assert e <= y + 90, (a, e)
    y += 108
y = 206
for a, b in right:
    d.rounded_rectangle([500, y, W - 52, y + 96], radius=12, fill=(255, 243, 236), outline=ACCENT, width=2)
    d.text((520, y + 12), a, font=f(23), fill=ACCENT)
    e = block(d, 520, y + 48, b, f(19), 380, MUTE, 1.5)
    assert e <= y + 90, (a, e)
    y += 108
d.rounded_rectangle([52, 662, W - 52, 706], radius=8, fill=(255, 239, 232))
d.text((77, 676), "试金石：你能忍住不写那一行 if，才说明你是真的信这个模型", font=f(21), fill=ACCENT)
save(img, "fig41-power-split.png")

img, d = canvas("自主演进的三把锁", "模型可以动手改自己的家，但钥匙在人手里", 640)
locks = [
    (ACC2, "锁 1 · 建议通道是纯建议", "提交 ≠ 生效。五维自评与演进建议必须经人工审阅", "submit → human review"),
    (ACCENT, "锁 2 · 执行权限分三级", "仅建议 / 白名单局部执行 / 全面执行，由人配置", "config: 3 levels"),
    (ACC3, "锁 3 · 边界演进完成登记归人", "涉边界的演进，executor=human，模型不能自己宣布完成", "executor=human"),
]
y = 172
for c, t, desc, tag in locks:
    d.rounded_rectangle([52, y, W - 52, y + 128], radius=14, fill=(250, 250, 251), outline=c, width=3)
    d.rounded_rectangle([53, y, 66, y + 128], radius=4, fill=c)
    d.text((86, y + 14), t, font=f(26), fill=c)
    e = block(d, 86, y + 56, desc, f(20), W - 200, INK, 1.5)
    assert e <= y + 92, (t, e)
    d.text((86, y + 98), tag, font=f(18), fill=MUTE)
    y += 148
d.rounded_rectangle([52, 624, W - 52, 668], radius=8, fill=(246, 248, 250))
d.text((77, 638), "验证结论若为「未验证」，如实标注 unverified——不允许用「看起来成功」充数", font=f(20), fill=NAVY)
save(img, "fig42-evolution-locks.png")
print("FIG_D14_DONE")
