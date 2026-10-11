"""Daily-06 original diagrams; conceptual examples, not Exa dataset images."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
import hashlib
OUT=Path(__file__).resolve().parents[1]/"img";OUT.mkdir(exist_ok=True)
CJK="/System/Library/Fonts/Hiragino Sans GB.ttc"
W,H=1200,720
BG="#F6F9FD"; NAVY="#172840"; MUTED="#52677C"; BLUE="#2563EB"
TEAL="#0F857B"; ORANGE="#E48132"; RED="#BD4650"; LINE="#D8E3EF"; WHITE="#FFFFFF"
def F(n):return ImageFont.truetype(CJK,n)
def t(d,xy,s,n=26,c=NAVY):d.text(xy,s,font=F(n),fill=c)
def box(d,r,fill=WHITE):d.rounded_rectangle(r,radius=17,fill=fill,outline=LINE,width=2)
def frame(h,s):
 im=Image.new("RGB",(W,H),BG);d=ImageDraw.Draw(im)
 d.rectangle((0,0,W,14),fill=BLUE);t(d,(56,36),h,43);t(d,(57,106),s,24,MUTED)
 d.line((57,157,1143,157),fill=LINE,width=3);return im,d
def save(im,n):
 p=OUT/n;im.save(p,optimize=True);print(n,im.size,p.stat().st_size,hashlib.sha256(p.read_bytes()).hexdigest())

im,d=frame("找到对象 ≠ 整行正确 ≠ 每项正确","以一个虚构的三家机构列表为例，说明搜索评分单元的区别")
head=["机构","所在地","类别","官网","整行"]
xs=[73,308,535,783,996]
for i,col in enumerate(head):t(d,(xs[i],211),col,29,BLUE)
d.line((58,259,1141,259),fill=LINE,width=3)
table=[
("机构 A","已核实","已核实","已核实","正确"),
("机构 B","已核实","待核实","已核实","不完整"),
("机构 C","待核实","已核实","待核实","不完整")]
for i,row in enumerate(table):
 y=276+i*94;box(d,(57,y,1142,y+84))
 for j,val in enumerate(row):t(d,(xs[j],y+21),val,27,TEAL if val in ("已核实","正确") else ORANGE if val in ("待核实","不完整") else NAVY)
d.rounded_rectangle((61,589,1139,665),radius=15,fill="#E7EFFC")
t(d,(78,601),"Discovery 看“有哪些机构”；Row 看“整行全对”；Item 看“逐字段”。",25,NAVY)
save(im,"fig22-search-three-scores.png")

im,d=frame("后端返回结果，仍要区分信源质量","LFL web_search 单查询中的部分失败与疑似词典降级提示")
box(d,(58,196,422,360));box(d,(450,196,1140,360))
t(d,(87,225),"输入：搜索问题",32,BLUE);t(d,(87,284),"例如：某项目动态",26,MUTED)
t(d,(475,225),"搜索后端候选结果",32,TEAL)
t(d,(475,284),"可能包含网页、词条或失败状态",26,MUTED)
d.line((424,277,448,277),fill=BLUE,width=5)
for i,(head,sub,col,fill) in enumerate([
("正常网页证据","记录来源并继续核验",TEAL,"#E4F5EF"),
("疑似词典降级","保留结果并显式警示",ORANGE,"#FFF1E4"),
("后端不可用","记录失败、不伪装结果",RED,"#F9E8EA")]):
 y=388+i*88;box(d,(73,y,1128,y+78),fill)
 t(d,(103,y+18),head,29,col);t(d,(481,y+22),sub,26,NAVY)
save(im,"fig23-search-fallback-flag.png")

im,d=frame("一份可继续调查的 AI 搜索底稿","将不确定性留在表里，而不是悄悄从答案里删掉")
cases=[
("已发现 · 已核实","字段和来源均能回查",TEAL),
("已发现 · 待核实","实体存在，部分属性缺证据",BLUE),
("候选 · 已排除","不满足条件，不算有效命中",ORANGE),
("未知 · 未覆盖","检索未完成，禁止“全部”结论",RED)]
for i,(head,detail,col) in enumerate(cases):
 x=62+(i%2)*547;y=193+(i//2)*209
 box(d,(x,y,x+522,y+181))
 d.rounded_rectangle((x+25,y+25,x+45,y+76),radius=7,fill=col)
 t(d,(x+66,y+26),head,30,NAVY)
 t(d,(x+27,y+104),detail,25,MUTED)
d.rounded_rectangle((60,629,1140,680),radius=13,fill="#E8EFFB")
t(d,(81,635),"结果越清楚地写出证据缺口，越便于人工或程序复核。",26,NAVY)
save(im,"fig24-search-evidence-states.png")
