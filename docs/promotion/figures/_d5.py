"""Daily-05 original educational figures; generated from the article's cited facts."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import hashlib
ROOT=Path(__file__).resolve().parents[1]/"img"
ROOT.mkdir(exist_ok=True)
CJK="/System/Library/Fonts/Hiragino Sans GB.ttc"
W,H=1200,720
NAVY="#172840"; MUTED="#52677C"; BLUE="#2563EB"; BG="#F6F9FD"
LINE="#DAE3EE"; TEAL="#0F857B"; ORANGE="#E48132"; RED="#BD4650"; WHITE="#FFFFFF"
def F(n):return ImageFont.truetype(CJK,n)
def t(d,xy,s,n=28,c=NAVY):d.text(xy,s,font=F(n),fill=c)
def bg(head,sub):
 im=Image.new("RGB",(W,H),BG);d=ImageDraw.Draw(im)
 d.rectangle((0,0,W,14),fill=BLUE);t(d,(56,34),head,44);t(d,(58,104),sub,24,MUTED)
 d.line((56,157,1144,157),fill=LINE,width=3);return im,d
def box(d,rect,col=WHITE):d.rounded_rectangle(rect,radius=20,fill=col,outline=LINE,width=2)
def save(im,name):
 path=ROOT/name;im.save(path,optimize=True)
 print(name,im.size,path.stat().st_size,hashlib.sha256(path.read_bytes()).hexdigest())
im,d=bg("同一次浏览器操作，为什么评分可能不同？","Odysseys2（2026年10月，研究项目方报告；论文仍待发表）")
box(d,(60,194,574,562));box(d,(626,194,1140,562))
t(d,(89,229),"截图与动作评审",33,BLUE);t(d,(655,229),"查看最终交付文件",33,TEAL)
for i,s in enumerate(["它访问过正确的网页吗？","某一帧是否出现了答案？","分项评分是否满足？"]):t(d,(89,306+i*56),s,27,MUTED)
for i,s in enumerate(["Excel 的每行是否完整？","数值能否追溯来源？","有没有编造或漏项？"]):t(d,(655,306+i*56),s,27,MUTED)
d.rounded_rectangle((76,483,558,542),radius=12,fill="#E7EFFC")
t(d,(103,493),"成绩范围：77—96 / 100",31,BLUE)
d.rounded_rectangle((642,483,1124,542),radius=12,fill="#E3F3EF")
t(d,(669,493),"成绩范围：2—85 / 100",31,TEAL)
t(d,(64,613),"同一批尝试、14种设置；分数差异来自不同验收方法，非模型突然倒退。",24,MUTED)
save(im,"fig19-browser-grading.png")

im,d=bg("浏览器 Agent 的交付有四层证据","看到页面只是第一层；越往下越接近可用成果")
steps=[
("01","访问证据","网站、页面、环境正确？",BLUE),
("02","动作证据","执行的是获授权的目标操作？","#418AC4"),
("03","交付证据","文件、列名、附件与数量正确？",TEAL),
("04","事实证据","每个关键字段均有可追溯来源？",ORANGE)]
for i,(n,head,sub,col) in enumerate(steps):
 y=183+i*112;box(d,(60,y,1136,y+95))
 d.rounded_rectangle((78,y+15,157,y+79),radius=16,fill=col)
 t(d,(93,y+24),n,31,WHITE)
 t(d,(184,y+18),head,32)
 t(d,(492,y+24),sub,28,MUTED)
 if i<3:t(d,(1110,y+92),"↓",20,BLUE)
d.rounded_rectangle((64,645,1136,694),radius=13,fill="#F7E9E9")
t(d,(80,650),"上层证据成立 ≠ 下层自动成立；缺证据时应该记“待核验”。",26,RED)
save(im,"fig20-browser-artifact-gates.png")

im,d=bg("点击成功 ≠ 最终业务结果成功","同一件事至少有三个可分离的验证状态")
stages=[
("1","浏览器输入事件","目标已确定，动作已派发","#E8EEFE",BLUE),
("2","平台接收回执","可能进入队列、审核或同步","#E1F3EE",TEAL),
("3","公开状态独立回读","旧记录ID、正文和图片均核实","#FFF2E7",ORANGE)]
for i,(n,title,sub,back,accent) in enumerate(stages):
 x=53+i*376;box(d,(x,220,x+351,518),back)
 d.ellipse((x+22,244,x+82,304),fill=accent)
 t(d,(x+42,251),n,30,WHITE)
 t(d,(x+22,344),title,30)
 t(d,(x+23,404),sub,24,MUTED)
 if i<2:
  d.line((x+353,365,x+374,365),width=4,fill=BLUE)
  d.polygon([(x+375,365),(x+365,358),(x+365,372)],fill=BLUE)
d.rounded_rectangle((61,585,1137,661),radius=18,fill="#ECF2FA")
t(d,(88,602),"例：编辑器说“提交成功”，也可能需要等待后续公开页面可见。",26,NAVY)
save(im,"fig21-browser-receipts.png")
