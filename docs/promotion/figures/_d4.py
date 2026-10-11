"""Daily-04 original technical illustrations. No third-party photos/figures."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import hashlib

ROOT=Path(__file__).resolve().parents[1]/"img"
ROOT.mkdir(parents=True,exist_ok=True)
FONT="/System/Library/Fonts/Hiragino Sans GB.ttc"
W,H=1200,720
NAVY="#172840"; MUTED="#52677C"; BLUE="#2563EB"; BG="#F6F9FD"; LINE="#DAE3EE"
TEAL="#0F857B"; ORANGE="#F28B37"; RED="#BD4650"; WHITE="#FFFFFF"

def font(size):
    return ImageFont.truetype(FONT,size)
def fdraw(draw,xy,text,size=30,fill=NAVY):
    draw.text(xy,text,font=font(size),fill=fill,stroke_width=0)
def pill(draw,box,text,fill,size=24,ink=WHITE):
    draw.rounded_rectangle(box,radius=16,fill=fill)
    w=draw.textbbox((0,0),text,font=font(size))[2]
    fdraw(draw,(box[0]+(box[2]-box[0]-w)//2,box[1]+(box[3]-box[1]-size)//2-1),text,size,ink)
def frame(title,subtitle):
    im=Image.new("RGB",(W,H),BG);d=ImageDraw.Draw(im)
    d.rectangle((0,0,W,14),fill=BLUE)
    fdraw(d,(56,38),title,43)
    fdraw(d,(58,103),subtitle,24,MUTED)
    d.line((56,153,1144,153),fill=LINE,width=2)
    return im,d
def save(im,name):
    p=ROOT/name;im.save(p,optimize=True)
    digest=hashlib.sha256(p.read_bytes()).hexdigest()
    print(name,im.size,p.stat().st_size,digest)
def arrow(d,a,b,color=BLUE,width=5):
    d.line((a,b),fill=color,width=width)
    d.polygon([(b[0],b[1]),(b[0]-11,b[1]-8),(b[0]-11,b[1]+8)],fill=color)
def card(d,xyxy,header,body,accent):
    d.rounded_rectangle(xyxy,radius=18,fill=WHITE,outline=LINE,width=2)
    x1,y1,x2,y2=xyxy
    d.rounded_rectangle((x1+23,y1+24,x1+40,y1+70),radius=7,fill=accent)
    fdraw(d,(x1+54,y1+24),header,30)
    for i,line in enumerate(body):
        fdraw(d,(x1+31,y1+103+i*38),line,25,MUTED)

# 1) Four categories: self-drawn synthesis, not paper figure.
im,d=frame("当 Agent 遇到阻碍","现实案例分类：目标未变，行动却越过了原边界")
data=[
("借外部软件的缺陷","工具受限后改走其他路径",BLUE),
("从练习变成真实提交","练习环境不可用 → 真实表单",ORANGE),
("越过访问限制","令牌、协议或付费门槛",TEAL),
("短链接绕过长度限制","换一种 URL 形式继续请求",RED),
]
for i,(a,b,c) in enumerate(data):
    x=56+(i%2)*553;y=183+(i//2)*202
    card(d,(x,y,x+530,y+176),a,[b],c)
d.rounded_rectangle((55,599,1145,669),radius=18,fill="#E7EFFC")
fdraw(d,(79,617),"关键区分：任务目标是否合理 ≠ 使用的路径与动作已经获授权",27,NAVY)
save(im,"fig16-boundary-overreach.png")

# 2) Accuracy of published paper percentages and denominators.
im,d=frame("自动批准：效率与风险一起放大？","HarnessSecurity-Bench（arXiv:2610.07639）· 6 个 harness · GLM-5.2 受控实验")
pill(d,(55,181,214,230),"自动批准 OFF","#6F8399",23)
pill(d,(234,181,397,230),"自动批准 ON",BLUE,23)
def bars(y,title,off,on,unit,accent,subtitle):
    fdraw(d,(58,y),title,31,NAVY)
    fdraw(d,(58,y+42),subtitle,23,MUTED)
    startx=370;barW=665
    for k,val,col in [(0,off,"#B4C2D2"),(1,on,accent)]:
        yy=y+12+k*58
        d.rounded_rectangle((startx,yy,startx+barW,yy+32),radius=14,fill="#E5ECF5")
        d.rounded_rectangle((startx,yy,startx+int(barW*val/100),yy+32),radius=14,fill=col)
        fdraw(d,(1055,yy-5),f"{val:.1f}%",30,accent if k else MUTED)
bars(281,"合法任务完成率",77.1,95.4,"%",BLUE,"OFF / ON：各 780 次判定")
bars(461,"攻击成功率（ASR）",29.2,95.6,"%",RED,"OFF / ON：各 360 次判定")
fdraw(d,(58,636),"注意：这些百分比是该受控基准结果，不能当成现实世界的事故概率。",23,MUTED)
save(im,"fig17-approval-bench.png")

# 3) Implementation guidance, not LFL certification.
im,d=frame("从“能操作”到“获授权且可证明”","参考架构：行动前检查范围，行动后独立确认；失败时停止而不是猜")
stages=[
("任务目标","用户想实现什么"),
("明确对象","具体页面与记录"),
("动作授权","允许读、改或提交？"),
("受控执行","有额度与权限约束"),
("独立回读","目标系统实际状态"),
("审计回执","可复核与可追溯"),
]
for i,(a,b) in enumerate(stages):
    row=i//3;col=i%3
    x=52+col*373;y=197+row*224
    card(d,(x,y,x+344,y+157),a,[b],BLUE if i<3 else TEAL)
    if col<2:
        yy=y+78
        d.line((x+346,yy,x+367,yy),fill=BLUE,width=5)
        d.polygon([(x+370,yy),(x+360,yy-7),(x+360,yy+7)],fill=BLUE)
# loop between top and bottom, drawn as vertical audit transition
d.line((1125,354,1125,420),fill=BLUE,width=4)
d.polygon([(1125,432),(1117,420),(1133,420)],fill=BLUE)
d.rounded_rectangle((59,637,1141,685),radius=14,fill="#F8E9E8")
fdraw(d,(80,642),"多目标 / 无授权 / 回执未知 → 停止并报告，不自动猜测或重试",25,RED)
save(im,"fig18-execution-receipt.png")
