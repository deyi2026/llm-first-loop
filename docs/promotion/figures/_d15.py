# -*- coding: utf-8 -*-
"""D15 original image-first infographics. Every figure is a schematic, not telemetry."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "img"
ROOT.mkdir(parents=True, exist_ok=True)
W, H = 1200, 740
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"
FONTL = "/System/Library/Fonts/STHeiti Light.ttc"
C = {
    "bg": "#F7F9FC", "ink": "#17263B", "muted": "#54667A", "line": "#DCE5EF",
    "blue": "#275DAD", "blue_light": "#E4EDFC", "mint": "#137F78",
    "mint_light": "#E4F4F0", "amber": "#AF5C11", "amber_light": "#FFF1DA",
    "purple": "#7552A6", "purple_light": "#F1EAF9",
    "coral": "#B44340", "coral_light": "#FCECE8", "white": "#FFFFFF",
}

def font(sz, strong=True):
    return ImageFont.truetype(FONT if strong else FONTL, sz)

def T(d, x, y, s, sz=26, c="ink", strong=True):
    d.text((x, y), str(s), font=font(sz, strong), fill=C.get(c, c))

def center(d, x, y, s, sz=26, c="ink", strong=True):
    bb = d.textbbox((0, 0), str(s), font=font(sz, strong))
    T(d, x-(bb[2]-bb[0])/2, y, s, sz, c, strong)

def box(d, coords, bg="white", stroke="line", radius=24, width=2):
    d.rounded_rectangle(coords, radius=radius, fill=C.get(bg, bg),
                        outline=C.get(stroke, stroke), width=width)

def line(d, pts, c="line", w=5):
    d.line(pts, fill=C.get(c,c), width=w, joint="curve")

def arrow(d, x1, y1, x2, y2, c="blue", w=5):
    line(d, [(x1,y1),(x2,y2)], c, w)
    import math
    a=math.atan2(y2-y1,x2-x1)
    side=15
    for ang in (2.55,-2.55):
        xx=x2+side*math.cos(a+ang)
        yy=y2+side*math.sin(a+ang)
        line(d,[(x2,y2),(xx,yy)],c,w)

def base(num, title, sub):
    im=Image.new("RGB",(W,H),C["bg"])
    d=ImageDraw.Draw(im)
    d.rounded_rectangle((48,44,61,118),radius=6,fill=C["blue"])
    T(d,86,41,title,40)
    T(d,87,104,sub,20,"muted",False)
    line(d,[(52,154),(1148,154)],"line",2)
    line(d,[(52,689),(1148,689)],"line",2)
    T(d,54,699,"LFL 原创科普 · 图解 Agent 隐形调用链",17,"muted",False)
    T(d,990,699,"FIG "+str(num)+" / 06",17,"muted")
    return im,d

def save(im,num,slug):
    path=ROOT/f"fig{num}-{slug}.png"
    im.save(path,optimize=True)
    print(path, im.size)

# Figure 1 - original system map
im,d=base(43,"问一句，后台究竟发生了什么？","示意：一个人类问题可能引发多条模型调用；并非每条都收费")
box(d,(285,172,915,257),"blue_light","blue",25,3)
center(d,600,186,"你：帮我完成一份资料整理",33,"blue")
center(d,600,228,"人类只发送 1 条任务消息",20,"muted",False)
arrow(d,600,258,600,299,"blue")
box(d,(61,317,521,439),"white","blue",22,3)
T(d,92,334,"主 Agent",34,"blue")
T(d,92,385,"计划、工具、结果检查",23,"muted",False)
box(d,(679,317,1139,439),"white","mint",22,3)
T(d,710,334,"子 Agent",34,"mint")
T(d,710,385,"接手并执行某个子任务",23,"muted",False)
arrow(d,521,376,672,376,"mint",5)
T(d,541,341,"派发",18,"mint")
for x,col,n,what in ((50,"blue","① 主模型","一次或多次"),
                      (429,"mint","② 子模型","一次或多次"),
                      (808,"coral","③ 隐藏重试","可能额外发送")):
    box(d,(x,515,x+342,623),"white",col,18,3)
    center(d,x+171,528,n,27,col)
    center(d,x+171,577,what,20,"muted",False)
arrow(d,279,440,221,508,"blue",4)
arrow(d,918,440,601,507,"mint",4)
arrow(d,927,440,978,507,"coral",4)
box(d,(190,644,1010,677),"amber_light","amber",12,1)
center(d,600,647,"任务数 ≠ 逻辑模型调用数 ≠ 网络物理尝试数",20,"amber")
save(im,43,"one-prompt-many-calls")

# Figure 2 - join physical attempts to logical calls
im,d=base(44,"3 次逻辑调用，为什么可能有 5 次发送？","右侧每个卡片代表一条独立 attempt_id；数字是假想案例")
T(d,80,176,"逻辑调用",24,"blue")
T(d,500,176,"真实网络尝试（每张卡片是一条 attempt_id）",23,"ink")
rows=[
    ("A","查资料",[("A1","超时","coral"),("A2","返回","mint")]),
    ("B","交给子任务",[("B1","返回","mint")]),
    ("C","整合回答",[("C1","连接断开","coral"),("C2","返回","mint")]),
]
for idx,(key,task,attempts) in enumerate(rows):
    y=215+idx*139
    box(d,(68,y,360,y+105),"blue_light","blue",19,2)
    T(d,92,y+12,"调用 "+key,27,"blue")
    T(d,93,y+57,task,22,"ink",False)
    arrow(d,374,y+52,477,y+52,"blue",3)
    for j,(aid,status,col) in enumerate(attempts):
        xx=500+j*300
        box(d,(xx,y+7,xx+265,y+99),C[col+"_light"],col,16,2)
        T(d,xx+19,y+18,aid,28,col)
        T(d,xx+98,y+25,status,23,col)
        T(d,xx+18,y+65,"物理尝试",18,"muted",False)
box(d,(113,643,1086,679),"amber_light","amber",12,1)
center(d,600,647,"1 条用户消息   →   3 次逻辑调用   →   5 次物理尝试   ≠   5 笔收费",20,"amber")
save(im,44,"logical-vs-physical")

# Figure 3 - cached tokens is not money saved
im,d=base(45,"缓存命中 90%，不等于账单打 1 折","假想例子：输入 100,000 Token，输出 3,000 Token；价格随模型/供应商不同")
T(d,75,191,"输入 Token",28,"ink")
T(d,940,191,"100,000",32,"blue")
barx,bary,bw=73,257,1054
box(d,(barx,bary,barx+bw,bary+114),"white","line",18,2)
d.rounded_rectangle((barx+4,bary+4,barx+int(bw*0.9),bary+110),radius=14,fill=C["mint"])
d.rectangle((barx+int(bw*0.85),bary+4,barx+int(bw*0.9),bary+110),fill=C["mint"])
d.rounded_rectangle((barx+int(bw*0.9),bary+4,barx+bw-4,bary+110),radius=14,fill=C["amber"])
d.rectangle((barx+int(bw*0.9),bary+4,barx+int(bw*0.95),bary+110),fill=C["amber"])
T(d,104,273,"已缓存输入 90,000",31,"white")
T(d,104,319,"通常另计缓存输入价格",20,"white",False)
center(d,1073,288,"10,000",24,"white")
T(d,75,400,"输出 Token",28,"ink")
box(d,(75,459,604,518),"purple_light","purple",16,2)
T(d,101,468,"3,000 生成 Token",28,"purple")
box(d,(627,459,1125,518),"amber_light","amber",16,2)
T(d,647,470,"重试可能继续耗费资源",23,"amber")
box(d,(73,548,1125,646),"white","line",18,2)
T(d,98,561,"成本 ≠ Token 总数 × 一个价格",26,"coral")
T(d,98,610,"至少要分开看：未缓存输入 × 输入价 + 缓存输入 × 缓存价 + 输出 × 输出价",20,"muted",False)
save(im,45,"cache-not-free")

# Figure 4 - four denominators
im,d=base(46,"一张漂亮的统计表，可能藏了四种分母","同一组假想数据：1 项任务，3 次逻辑调用，5 次物理尝试，103,000 Token")
cards=[
    (62,177,"01","任务层","1 项任务","完成了吗？交付物正确吗？","blue","blue_light"),
    (620,177,"02","逻辑调用层","3 次逻辑调用","模型决策走了几轮？","mint","mint_light"),
    (62,412,"03","网络物理层","5 次 attempt","有没有隐藏重试、失败或未结算？","coral","coral_light"),
    (620,412,"04","用量层","103,000 Token","缓存、模型和输出价格如何拆？","purple","purple_light")
]
for x,y,num,h,v,sub,accent,soft in cards:
    box(d,(x,y,x+519,y+208),"white","line",22,2)
    box(d,(x+18,y+21,x+100,y+83),soft,accent,13,1)
    center(d,x+59,y+32,num,29,accent)
    T(d,x+121,y+20,h,26,accent)
    T(d,x+28,y+88,v,31,"ink")
    T(d,x+29,y+157,sub,18,"muted",False)
box(d,(215,644,985,678),"amber_light","amber",10,1)
center(d,600,647,"分母不同，排名、缓存率和效率结论可能完全不同",20,"amber")
save(im,46,"four-denominators")

# Figure 5 - epistemic states
im,d=base(47,"最危险的数字，不是 0，是「假装知道」","读实物回执时应区分：已证明、尚不完整、发生冲突")
states=[
    ("能算","settled + 完整 usage","同一 attempt_id 去重","只汇总有证据的 Token","mint","mint_light"),
    ("先别算","opened 但未 settled","发送未完成 ≠ 已收费","缺缓存字段则标未知","amber","amber_light"),
    ("必须暂停","同 ID 回执互相冲突","可能重复或数据损坏","冲突使用量不参与求和","coral","coral_light"),
]
for j,(title,l1,l2,l3,accent,soft) in enumerate(states):
    x=51+j*384
    box(d,(x,192,x+362,600),"white",accent,22,3)
    box(d,(x+20,214,x+342,292),soft,accent,17,1)
    center(d,x+181,229,title,37,accent)
    T(d,x+26,331,l1,23,"ink")
    line(d,[(x+26,382),(x+335,382)],"line",2)
    T(d,x+26,408,l2,21,"muted",False)
    line(d,[(x+26,463),(x+335,463)],"line",2)
    T(d,x+26,491,l3,21,accent,False)
box(d,(104,623,1096,672),"blue_light","blue",13,1)
center(d,600,632,"缓存率 = 已缓存输入 / 输入总量；仅在覆盖完整且分母有效时展示",20,"blue")
save(im,47,"receipt-evidence-states")

# Figure 6 - checklist
im,d=base(48,"看到 Agent 成本报告，先问这 6 个问题","可截图保存：这是一份核对口径的清单，而不是任何产品的性能排名")
checks=[
    ("01","用户发了几条任务？","先确定任务分母"),
    ("02","调用了几次模型？","包括主代理和子代理"),
    ("03","真实发送有几次？","别漏掉隐藏重试"),
    ("04","用量覆盖完整吗？","空值不能变成零"),
    ("05","缓存 Token 怎么算？","分清输入/缓存/输出"),
    ("06","有真实账单价格吗？","Token 不等于美元")
]
for i,(num,title,note) in enumerate(checks):
    col=i%2; row=i//2
    x=59+col*557; y=183+row*157
    accent=("blue","mint","coral","amber","purple","blue")[i]
    box(d,(x,y,x+523,y+141),"white","line",20,2)
    box(d,(x+18,y+20,x+91,y+91),C[accent+"_light"],accent,15,1)
    center(d,x+55,y+34,num,29,accent)
    T(d,x+107,y+17,title,25,"ink")
    T(d,x+107,y+74,note,20,"muted",False)
box(d,(185,664,1015,683),"amber_light","amber",8,1)
center(d,600,661,"先把「不知道」说清楚，再谈怎么优化",17,"amber")
save(im,48,"six-questions")

print("D15_SIX_IMAGES_DONE")
