"""Original LFL infographic series. No external visual assets.

Render: .venv/bin/python outputs/lfl-article-20261014-evening/gen_images.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "assets"
OUT.mkdir(parents=True, exist_ok=True)
W, H = 1280, 800
S = 2
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FALLBACK = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT = FONT if Path(FONT).exists() else FALLBACK
INK = "#14243C"
MUTED = "#55677E"
BG = "#F4F7FD"
NAVY = "#0F2441"
BLUE = "#2474DC"
CYAN = "#21ADBD"
GREEN = "#1EA879"
AMBER = "#D99C35"
RED = "#D25D68"
PANEL = "#FFFFFF"


def font(size, bold=False):
    return ImageFont.truetype(FONT, int(size * S), index=0)


def xy(p):
    return round(p * S)


def scaled(box):
    return tuple(xy(v) for v in box)


def text(draw, pos, s, size=25, color=INK, anchor=None, bold=False, spacing=8):
    draw.multiline_text((xy(pos[0]), xy(pos[1])), s, font=font(size, bold),
                        fill=color, anchor=anchor, spacing=xy(spacing))


def rect(draw, box, fill=PANEL, radius=22, outline=None, width=2):
    draw.rounded_rectangle(scaled(box), radius=xy(radius), fill=fill,
                           outline=outline, width=xy(width))


def line(draw, points, fill=BLUE, width=4, joint="curve"):
    draw.line([tuple(map(xy, p)) for p in points], fill=fill, width=xy(width), joint=joint)


def circ(draw, center, r, fill, outline=None, width=3):
    cx, cy = center
    draw.ellipse(scaled((cx-r, cy-r, cx+r, cy+r)), fill=fill,
                 outline=outline, width=xy(width))


def arrow(draw, a, b, color=BLUE, width=4):
    line(draw, [a, b], color, width)
    angle = math.atan2(b[1]-a[1], b[0]-a[0])
    h = 13
    for k in [-0.62, 0.62]:
        p = (b[0]-h*math.cos(angle+k), b[1]-h*math.sin(angle+k))
        line(draw, [p, b], color, width)


def pill(draw, box, s, bg, fg="#FFFFFF", size=21):
    rect(draw, box, bg, 28)
    text(draw, ((box[0]+box[2])/2, (box[1]+box[3])/2), s,
         size, fg, anchor="mm")


def sheet(draw, x, y, color=BLUE, w=96, h=112):
    rect(draw, (x, y, x+w, y+h), "#FFFFFF", 10, color, 3)
    for k in range(3):
        line(draw, [(x+19,y+32+k*23),(x+w-18,y+32+k*23)], color, 3)


def check(draw, x, y, color=GREEN):
    circ(draw, (x,y), 22, color)
    line(draw, [(x-10,y),(x-2,y+7),(x+13,y-10)], "white", 5)


def cross(draw, x, y, color=RED):
    circ(draw, (x,y), 22, color)
    line(draw,[(x-8,y-8),(x+8,y+8)],"white",4)
    line(draw,[(x+8,y-8),(x-8,y+8)],"white",4)


def question(draw, x, y):
    circ(draw, (x,y), 22, AMBER)
    text(draw,(x,y+1),"?",27,"white",anchor="mm")


def base(num, title, subtitle):
    im = Image.new("RGB", (W*S,H*S), BG)
    d = ImageDraw.Draw(im)
    d.rectangle(scaled((0,0,W,14)), fill=BLUE)
    pill(d, (70,53,164,102), f"{num:02d}", NAVY, size=24)
    text(d,(190,77),title,37,INK,anchor="lm",bold=True)
    text(d,(70,133),subtitle,23,MUTED)
    line(d,[(70,177),(1210,177)],"#E0E7F2",2)
    text(d,(1205,766),"LFL · llm-first-loop    /    原创架构示意 · 非实测截图",16,"#8493A7",anchor="ra")
    return im,d


def export(im,name):
    dest=OUT/name
    im.resize((W,H),Image.Resampling.LANCZOS).save(dest,optimize=True)
    print(dest, dest.stat().st_size)


def cover():
    im=Image.new("RGB",(W*S,H*S),NAVY)
    d=ImageDraw.Draw(im)
    for k in range(12):
        cx=780+(k%4)*130
        cy=60+(k//4)*260
        circ(d,(cx,cy),135,None,outline="#27496C",width=2)
    pill(d,(82,83,358,137),"LFL   ·   开源 Agent",BLUE,21)
    text(d,(87,230),"一句话，",74,"white",bold=True)
    text(d,(87,336),"到一次可核对的交付",67,"#D5F5FF",bold=True)
    text(d,(88,448),"8 张图，看懂大模型怎样从“回答”走向“做事”",29,"#BFD3EB")
    for i,(s,c) in enumerate([("任务",BLUE),("工具",CYAN),("回执",GREEN),("记忆",AMBER)]):
        pill(d,(90+i*166,545,218+i*166,605),s,c,20)
        if i<3: arrow(d,(221+i*166,575),(245+i*166,575),"#7B99BB",3)
    text(d,(89,746),"LLM-FIRST LOOP   /   v0.6.32   /   2026.10.14",20,"#809EBD")
    export(im,"00-cover.png")


def task():
    im,d=base(1,"一个需求，至少有三种不同的结果","不要把一条顺口的回复，当成一份已经验收的交付")
    rect(d,(65,225,530,626),"#FFFFFF",24)
    pill(d,(94,254,226,305),"用户指令",BLUE,20)
    text(d,(99,349),"“比较三种方案，",31,INK)
    text(d,(99,403),"做一份表格，",31,INK)
    text(d,(99,457),"每条结论附来源。”",31,INK)
    arrow(d,(558,431),(622,431),BLUE,5)
    for i,(head,sub,col) in enumerate([
       ("结果文件","表格/文档存在",BLUE),
       ("引用来源","关键资料可定位",CYAN),
       ("执行回执","成功/失败/未知",GREEN)]):
        y=238+i*140
        rect(d,(652,y,1194,y+118),"#FFFFFF",20)
        circ(d,(717,y+58),29,col)
        text(d,(783,y+40),head,30,INK,bold=True)
        text(d,(783,y+86),sub,22,MUTED)
    rect(d,(71,682,1207,737),"#E4F0FF",18)
    text(d,(638,709),"这是一段“假设任务”的教学示意，真实结果必须在对应工具和环境里验收。",21,BLUE,anchor="mm")
    export(im,"01-task.png")


def loop():
    im,d=base(2,"LFL 的核心：不是一句话，是一个循环","官方 README 的五阶段表达（下方箭头表示任务推进，而非固定耗时）")
    names=["消息进","理解","行动","真诚回答","记住"]
    desc=["接收需求","模型判断","调用工具","忠实汇报","保存线索"]
    colors=[BLUE,CYAN,"#4676C8",GREEN,AMBER]
    for i,(n,sub,c) in enumerate(zip(names,desc,colors)):
        x=60+i*250
        rect(d,(x,295,x+211,517),"#FFFFFF",26,c,3)
        circ(d,(x+105,348),31,c)
        text(d,(x+105,347),str(i+1),27,"white",anchor="mm")
        text(d,(x+105,415),n,31,INK,anchor="mm",bold=True)
        text(d,(x+105,468),sub,21,MUTED,anchor="mm")
        if i<4: arrow(d,(x+214,402),(x+244,402),c,4)
    rect(d,(153,577,1124,697),"#E9F3FF",24)
    text(d,(639,610),"程序反馈真实结果   ·   模型据此继续决定",28,BLUE,anchor="mm",bold=True)
    text(d,(639,661),"成功、异常、未完成都应该进入下一次判断",21,MUTED,anchor="mm")
    export(im,"02-loop.png")


def brain_hands():
    im,d=base(3,"谁在思考，谁在执行？","LFL 的 LLM-first 思路：模型优先判断，程序提供观察、执行与硬边界")
    rect(d,(70,236,489,602),"#EAF3FF",24,BLUE,3)
    pill(d,(114,274,303,325),"LLM · 大脑",BLUE,23)
    text(d,(111,379),"理解目标",37,INK,bold=True)
    text(d,(111,452),"规划下一步",37,INK,bold=True)
    text(d,(111,525),"判断证据够不够",31,INK)
    arrow(d,(515,413),(622,413),CYAN,6)
    rect(d,(654,236,1208,602),"#FFFFFF",24,CYAN,3)
    pill(d,(696,273,952,325),"Runtime · 手脚",CYAN,23)
    for i,(a,b) in enumerate([("看现场","检索/读取/浏览器感知"),("动手做","命令/浏览器操作"),("报事实","状态回执/审计记录")]):
        y=376+i*78
        circ(d,(719,y+4),16,[BLUE,CYAN,GREEN][i])
        text(d,(755,y),a,29,INK,anchor="lm",bold=True)
        text(d,(941,y),b,21,MUTED,anchor="lm")
    rect(d,(121,644,1164,709),"#FFF1DA",20)
    text(d,(640,676),"执行权限、协议和不可逆高风险边界不应交给模型自行“想象”",23,"#8A6123",anchor="mm")
    export(im,"03-brain-hands.png")


def receipts():
    im,d=base(4,"一句“已经好了”，需要什么证据？","一次操作至少要区分“成功”“失败”“尚未核验”")
    rows=[
       ("SUCCESS","操作成功","有可核实回执",GREEN),
       ("FAILURE","操作失败","记录报错和下一步",RED),
       ("UNKNOWN","未核验","不要把猜测写成结果",AMBER)]
    for i,(tag,head,sub,c) in enumerate(rows):
        y=231+i*155
        rect(d,(102,y,1174,y+133),"#FFFFFF",22)
        if i==0: check(d,164,y+66,c)
        if i==1: cross(d,164,y+66,c)
        if i==2: question(d,164,y+66)
        pill(d,(211,y+26,386,y+76),tag,c,18)
        text(d,(432,y+49),head,34,INK,anchor="lm",bold=True)
        text(d,(813,y+49),sub,24,MUTED,anchor="lm")
        line(d,[(227,y+103),(1093,y+103)],"#DFE8F4",2)
    pill(d,(366,722,924,760),"模型的表达 ≠ 外部世界的状态",NAVY,22)
    export(im,"04-receipts.png")


def surfaces():
    im,d=base(5,"三个入口，可以指向同一段工作","前提：正确配置共享会话与身份；并非所有聊天都会自动合流")
    for i,(name,sub,col) in enumerate([
      ("CLI","命令行 · --session",NAVY),
      ("WEB","浏览器工作台",BLUE),
      ("飞书","消息入口 · Bridge",CYAN)]):
        x=89+i*399
        rect(d,(x,237,x+320,444),"#FFFFFF",23,col,3)
        pill(d,(x+65,262,x+255,320),name,col,28)
        text(d,(x+160,377),sub,22,MUTED,anchor="mm")
        arrow(d,(x+160,445),(x+160,534),col,4)
    rect(d,(376,544,894,675),"#E5F6F4",25,CYAN,3)
    text(d,(635,591),"共享的会话上下文",35,INK,anchor="mm",bold=True)
    text(d,(635,638),"复用会话 ID · 条件满足才成立",21,MUTED,anchor="mm")
    export(im,"05-surfaces.png")


def memory():
    im,d=base(6,"记忆不是“背过就算”，而是有路径可查","当前窗口、压缩档案、事件日志各司其职；旧证据也要复核新鲜度")
    col=[BLUE,CYAN,AMBER]
    titles=["当前上下文","压缩档案与检索","事件日志与回放"]
    captions=["眼前这轮任务","需要时重新找回","动作与来源可追溯"]
    for i,(t,sub,c) in enumerate(zip(titles,captions,col)):
        x=86+i*400
        rect(d,(x,267,x+320,546),"#FFFFFF",24,c,3)
        circ(d,(x+160,347),46,c)
        text(d,(x+160,346),["1","2","3"][i],37,"white",anchor="mm")
        text(d,(x+160,427),t,29,INK,anchor="mm",bold=True)
        text(d,(x+160,482),sub,21,MUTED,anchor="mm")
        if i<2: arrow(d,(x+322,417),(x+389,417),c,4)
    rect(d,(181,622,1096,694),"#FEF3DF",22)
    text(d,(638,659),"注意：历史记录 ≠ 今天仍然成立的事实",27,"#90631F",anchor="mm",bold=True)
    export(im,"06-memory.png")


def approval():
    im,d=base(7,"能做事，也需要有“停下确认”的时刻","这是治理机制示意；真实批准、工具许可与执行结果是不同的事")
    nodes=[("模型提出动作",BLUE),("权限与人工审批",AMBER),("获准后受控执行",CYAN),("独立核验结果",GREEN)]
    for i,(s,c) in enumerate(nodes):
        x=60+i*306
        rect(d,(x,317,x+269,502),"#FFFFFF",22,c,3)
        circ(d,(x+135,364),26,c)
        text(d,(x+135,363),str(i+1),23,"white",anchor="mm")
        text(d,(x+135,442),s,25,INK,anchor="mm",bold=True)
        if i<3: arrow(d,(x+273,408),(x+301,408),c,4)
    rect(d,(179,556,1113,677),"#FCECEB",23)
    cross(d,242,618,RED)
    text(d,(295,593),"未获授权 → 不扩大范围",26,INK,bold=True)
    text(d,(295,644),"已获授权 → 仍要检查是否真的执行、是否真的成功",22,MUTED)
    export(im,"07-approval.png")


def get_started():
    im,d=base(8,"开源 LFL，从一个最小任务开始","Apache-2.0  |  v0.6.32  |  Python ≥ 3.13（截至本文核对）")
    rect(d,(86,224,1192,690),NAVY,28)
    pill(d,(128,263,430,321),"GitHub / deyi2026",BLUE,23)
    text(d,(128,371),"github.com/deyi2026/llm-first-loop",38,"white",bold=True)
    line(d,[(130,404),(1135,404)],"#385574",2)
    text(d,(133,466),"01  安装依赖",27,"#9CE7F2")
    text(d,(500,466),"uv sync --frozen --extra dev",26,"white")
    text(d,(133,530),"02  配置 API",27,"#9CE7F2")
    text(d,(500,530),"按 README 设置模型供应商与密钥",25,"white")
    text(d,(133,594),"03  运行任务",27,"#9CE7F2")
    text(d,(500,594),".venv/bin/python -m llm_loop.cli \"你好\"",23,"white")
    text(d,(128,659),"先跑通最小闭环，再按需接入浏览器、Web 与飞书",20,"#A9C1DB")
    export(im,"08-get-started.png")


def main():
    cover()
    for fn in [task,loop,brain_hands,receipts,surfaces,memory,approval,get_started]:
        fn()


if __name__ == "__main__":
    main()
