# -*- coding: utf-8 -*-
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _draw import *

# ---------- fig35: 四道防线 ----------
img, d = canvas("四道防线，各守一段", "围栏挡动手，审计抓分身", 636)
rows = [
    (176, (110,118,138), "底座 · 运行时围栏（既有）", "父代理运行期内，子代理 14/14 次命令执行全部被拒；挡得住动手，挡不住拉起孙代理（实测 1/1 成功）"),
    (282, ACC3,           "一 · 任务书纪律", "逐字写入禁令清单与后果声明；要写成可判定句子，「不要自行结算」这类抽象叮嘱实测不被内化"),
    (388, NAVY,           "二 · 结算审计", "结算回执自带完整工具轨迹，逐条比对禁令清单，「拉起子代理」类单列复核——探针轨迹按此审计即命中"),
    (494, ACCENT,         "三 · 违规处置", "本次结果拒收 + 档案归档退役 + 房间日志记违规 + 孙代拓扑核查清退"),
]
for y, col, head, body in rows:
    d.rounded_rectangle([52, y, W-52, y+92], 10, fill=(255,255,255), outline=col, width=2)
    d.rectangle([52, y, 60, y+92], fill=col)
    d.text((76, y+12), head, font=f(20), fill=col)
    block(d, 76, y+42, body, f(16), 830, INK)
save(img, "fig35-defense-layers.png")

# ---------- fig36: 审批链四道锁 ----------
img, d = canvas("审批链上的四道锁", "令牌只给自己，损坏即停机，替换无窗口，密码不收", 640)
cards = [
    (0, 0, "锁一 · 偷读令牌", "审批令牌 owner-private：写入禁跟随符号链接，打开后复验文件属性；遗留宽松权限文件读取前原地收紧", ACCENT),
    (1, 0, "锁二 · 篡改重置", "状态文件损坏一律 fail-closed 拒绝覆盖——不再是「当空的重新来」，那等于允许重置审批记录", ACCENT),
    (0, 1, "锁三 · 替换窗口", "原子替换的临时文件改随机名 + 独占创建 + 0600 + 同步落盘，消除窗口期内令牌对同机其他用户可读", ACC3),
    (1, 1, "锁四 · 密码入参", "Web 审批表单只认白名单字段：密码类不收也不回显；校验失败时，被审批的命令不执行", ACC3),
]
CW, CH = 430, 176
for cx, cy, head, body, col in cards:
    x = 60 + cx * (CW + 20)
    y = 168 + cy * (CH + 20)
    d.rounded_rectangle([x, y, x+CW, y+CH], 12, fill=(255,255,255), outline=col, width=2)
    d.rectangle([x, y, x+CW, y+44], fill=col)
    d.text((x+20, y+10), head, font=f(21), fill=(255,255,255))
    block(d, x+20, y+58, body, f(17), CW-40, INK)
d.rounded_rectangle([60, 552, W-60, 596], 8, fill=(255,240,236))
d.text((80, 564), "内部审批门 ≠ 操作系统管理员授权：两层权限各自把守，不能互相替代", font=f(18), fill=ACCENT)
save(img, "fig36-approval-locks.png")
print("done")
