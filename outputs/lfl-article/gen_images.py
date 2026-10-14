# -*- coding: utf-8 -*-
"""Generate promo figures for LFL (llm-first-loop). Facts sourced from repo docs + runtime receipts 2026-10-14."""
import os, math
import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Rectangle
from matplotlib.colors import LinearSegmentedColormap

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
os.makedirs(ASSETS, exist_ok=True)

FONT_FILES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]
resolved = []
for p in FONT_FILES:
    if os.path.exists(p):
        try:
            fm.fontManager.addfont(p)
            resolved.append(fm.FontProperties(fname=p).get_name())
        except Exception as e:
            print("font skip:", p, e)
plt.rcParams["font.sans-serif"] = resolved + ["Hiragino Sans GB", "Arial Unicode MS", "sans-serif"]
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["axes.unicode_minus"] = False
print("fonts resolved:", resolved)

NAVY = "#16324F"; INK = "#1F2937"; GRAY = "#6B7280"
BLUE = "#2563EB"; CYAN = "#0891B2"; GREEN = "#10B981"; AMBER = "#F59E0B"
RED = "#EF4444"; PURPLE = "#8B5CF6"

def new_fig(w=11, h=6.2, xlim=(0, 110), ylim=(0, 62)):
    fig, ax = plt.subplots(figsize=(w, h), dpi=170)
    ax.set_xlim(*xlim); ax.set_ylim(*ylim); ax.axis("off")
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    return fig, ax

def box(ax, x, y, w, h, text="", fc="#FFFFFF", ec=NAVY, lw=1.6, radius=1.1, ls="-", zorder=2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={radius}",
                 fc=fc, ec=ec, lw=lw, linestyle=ls, zorder=zorder))

def txt(ax, x, y, s, fs=12, color=INK, weight="normal", ha="center", va="center", zorder=5, ls=1.45, rotation=0):
    ax.text(x, y, s, fontsize=fs, color=color, fontweight=weight, ha=ha, va=va,
            zorder=zorder, linespacing=ls, rotation=rotation)

def arrow(ax, p1, p2, color=NAVY, lw=2.0, rad=0.0, ms=15, zorder=3):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=ms, color=color,
                 lw=lw, connectionstyle=f"arc3,rad={rad}", zorder=zorder))

def title(ax, s, y=58):
    txt(ax, 55, y, s, fs=16.5, color=NAVY, weight="bold")

def cw(s):
    return sum(1.5 if ord(ch) > 0x2E80 else 0.82 for ch in s)

def save(fig, name):
    path = os.path.join(ASSETS, name)
    fig.savefig(path, dpi=170, facecolor="white")
    plt.close(fig)
    print("saved", path)

# ---------- 0 banner ----------
def banner():
    fig, ax = new_fig(11, 3.7, (0, 110), (0, 37))
    cmap = LinearSegmentedColormap.from_list("bg", ["#0E2239", "#1D4E79"])
    ax.imshow(np.linspace(0, 1, 256).reshape(-1, 1), cmap=cmap, extent=(0, 110, 0, 37),
              aspect="auto", zorder=-1, origin="lower")
    for (cx_, cy_, r_) in [(96, 30, 16), (8, 4, 12), (74, -6, 18)]:
        ax.add_patch(Circle((cx_, cy_), r_, fill=False, ec="#7FB6E8", lw=1.2, alpha=0.35, zorder=0))
    txt(ax, 14, 21.5, "LFL", fs=52, color="white", weight="bold")
    txt(ax, 14, 12.5, "llm-first-loop", fs=13, color="#9FD8FF")
    ax.plot([29, 29], [7, 31], color="#3E6D99", lw=1.2)
    txt(ax, 35, 27.5, "让大模型可信赖地行动的智能体运行时", fs=20, color="white", weight="bold", ha="left")
    txt(ax, 35, 21.5, "消息进 → 理解 → 行动 → 真诚回答 → 记住", fs=13, color="#9FD8FF", ha="left")
    x = 35
    for ctext in ["开源 Apache-2.0", "v0.6.32", "Python ≥ 3.13", "CLI · Web · 飞书"]:
        w = cw(ctext) + 4.4
        box(ax, x, 7, w, 6.5, "", fc="#28527D", ec="#7FB6E8", lw=1.0, radius=3.2)
        txt(ax, x + w / 2, 10.25, ctext, fs=10.5, color="white")
        x += w + 3
    txt(ax, 108, 2.2, "程序最小化 · 规则驱动 · 自主演进闭环", fs=10, color="#CFE8FF", ha="right")
    save(fig, "img0_banner.png")

# ---------- 1 positioning ----------
def positioning():
    fig, ax = new_fig(11, 6.4, (0, 110), (0, 64))
    title(ax, "LFL 是什么：大模型内核 + 程序感官与手脚 + 记忆与审计", y=60)
    box(ax, 4, 42, 24, 12, "", fc="#FFF7E6", ec="#F59E0B", lw=1.6)
    txt(ax, 16, 50.5, "文档规则", fs=12, color="#B45309", weight="bold")
    txt(ax, 16, 46.2, "docs/ai_rules.md\n判断纪律 · 唯一真值源", fs=9.3, color=INK)
    box(ax, 82, 42, 24, 12, "", fc="#FEF2F2", ec=RED, lw=1.6)
    txt(ax, 94, 50.5, "硬边界不移交", fs=12, color="#B91C1C", weight="bold")
    txt(ax, 94, 46.2, "灾难安全硬阻断\n严格 function-calling 协议", fs=9.3, color=INK)
    box(ax, 36, 41, 38, 14, "", fc=NAVY, ec=NAVY)
    txt(ax, 55, 50.5, "LLM 大模型内核", fs=15, color="white", weight="bold")
    txt(ax, 55, 45.5, "策略 · 判断 · 生成", fs=10.5, color="#BFD7EE")
    ax.plot([28, 36], [48, 48], ls=":", color="#94A3B8", lw=1.8, zorder=1)
    ax.plot([74, 82], [48, 48], ls=":", color="#94A3B8", lw=1.8, zorder=1)
    box(ax, 8, 17, 94, 19, "", fc="#EFF6FF", ec=BLUE, lw=2.0)
    txt(ax, 55, 32.5, "LFL 运行时 Harness —— 程序是感官与手脚，不替 AI 思考", fs=12.5, color=NAVY, weight="bold")
    chips = [
        ("感知", "运行时自省\narchitecture_status"),
        ("执行", "工具调用\n严格回执"),
        ("记忆", "证据 · 档案\n经验检索"),
        ("边界", "超时 · 原子写\n全程审计"),
    ]
    for i, (head, body) in enumerate(chips):
        x = 12 + i * 22.5
        box(ax, x, 19, 21, 11, "", fc="white", ec="#93C5FD", lw=1.4)
        txt(ax, x + 10.5, 27.3, head, fs=11.5, color=BLUE, weight="bold")
        txt(ax, x + 10.5, 22.7, body, fs=8.8, color=GRAY)
    for name, x in [("CLI 命令行", 12), ("Web 管理台 :8903", 44), ("飞书长连接桥", 76)]:
        box(ax, x, 4, 22, 8, "", fc="#ECFDF5", ec=GREEN, lw=1.6)
        txt(ax, x + 11, 8, name, fs=11.5, color="#047857", weight="bold")
        arrow(ax, (x + 11, 12.5), (x + 11, 16.6), color="#94A3B8", lw=1.8)
    txt(ax, 55, 1.2, "三端共享同一会话与记忆：一端交代任务，另一端接着聊", fs=10, color=GRAY)
    save(fig, "img1_positioning.png")

# ---------- 2 core loop ----------
def core_loop():
    fig, ax = new_fig(11, 6.2)
    title(ax, "核心循环：五阶段状态机，一步一景、步步留痕")
    cx, cy, R = 40, 28, 17.5
    stages = [
        ("① 消息进", "真人指令 / 事件进入", BLUE),
        ("② 理解", "区分事实与假设", CYAN),
        ("③ 行动", "调工具 · 取回执", GREEN),
        ("④ 真诚回答", "不夸大 · 不虚构完成", AMBER),
        ("⑤ 记住", "事件日志 · 记忆沉淀", PURPLE),
    ]
    pts = []
    for i in range(5):
        ang = math.radians(90 - 72 * i)
        pts.append((cx + R * math.cos(ang), cy + R * math.sin(ang)))
    w, h = 19, 8.5
    for (px, py), (name, sub, col) in zip(pts, stages):
        box(ax, px - w / 2, py - h / 2, w, h, "", fc="white", ec=col, lw=2.2, radius=1.4)
        txt(ax, px, py + 1.7, name, fs=13, color=col, weight="bold")
        txt(ax, px, py - 2.0, sub, fs=9.3, color=GRAY)
    for i in range(5):
        p1 = np.array(pts[i]); p2 = np.array(pts[(i + 1) % 5])
        u = (p2 - p1) / np.linalg.norm(p2 - p1)
        off = math.sqrt((w / 2 * u[0]) ** 2 + (h / 2 * u[1]) ** 2) + 1.3
        arrow(ax, tuple(p1 + u * off), tuple(p2 - u * off), color="#94A3B8", lw=2.0, rad=0.24)
    txt(ax, cx, cy + 3, "LoopEngine", fs=14, color=NAVY, weight="bold")
    txt(ax, cx - 1.5, cy - 1.8, "程序管回执与边界\n模型管判断与表达", fs=9.2, color=GRAY)
    box(ax, 74, 8, 33, 40, "", fc="#F8FAFC", ec="#CBD5E1", lw=1.2)
    txt(ax, 90.5, 44, "设计要点", fs=12.5, color=NAVY, weight="bold")
    bullets = ["每步可观测：动作必有回执", "失败不静默：报错完整透传", "每步可追溯：事件日志记录",
               "记住能找回：检索与档案", "授权不越界：下层不扩上层"]
    y = 38.5
    for b in bullets:
        txt(ax, 77, y, "•", fs=12, color=BLUE, ha="left")
        txt(ax, 80, y, b, fs=10.3, color=INK, ha="left")
        y -= 6.2
    save(fig, "img2_core_loop.png")

# ---------- 3 three layers ----------
def three_layers():
    fig, ax = new_fig(11, 6.2)
    title(ax, "三层权威边界：把'谁说了算'写进架构")
    layers = [
        (43, "#FFF7E6", "#D97706", "L3 用户层 · 授权真值",
         "真人指令 = 任务授权唯一真值；远端写 / 合并删除 / 凭证 / 公开发布由真人拍板"),
        (27, "#EFF6FF", "#2563EB", "L2 模型层 · 策略与诚实",
         "任务策略 · 完成判断 · 证据引用 · 失败如实报告；禁止扩大授权、禁止伪造精确"),
        (11, "#F0FDF4", "#059669", "L1 程序层 · 机器裁决",
         "安全硬边界 · 超时与预算 · 原子写与快照 · Evidence 持久化 · 协议校验"),
    ]
    for y, fc, ec, head, body in layers:
        box(ax, 18, y, 64, 12, "", fc=fc, ec=ec, lw=2.0)
        txt(ax, 50, y + 8.6, head, fs=13.5, color=ec, weight="bold")
        txt(ax, 50, y + 3.8, body, fs=9.8, color=INK)
    arrow(ax, (99, 53), (99, 13), color="#D97706", lw=2.6)
    txt(ax, 103.5, 33, "授权下行  L3 → L2 → L1", fs=10.5, color="#B45309", rotation=-90)
    arrow(ax, (11, 13), (11, 53), color="#059669", lw=2.6)
    txt(ax, 6.8, 33, "证据回流  L1 → L2 → L3", fs=10.5, color="#047857", rotation=90)
    txt(ax, 50, 6, "铁律：下层不得扩大上层授权；事实争议回到 L1 —— EvidenceRef 可随时水合复核原文", fs=10.5, color=GRAY)
    save(fig, "img3_three_layers.png")

# ---------- 4 honesty ----------
def honesty():
    fig, ax = new_fig(11, 6.4, (0, 110), (0, 64))
    title(ax, "诚实工程：让'说完成'变成可核验的事", y=60)
    box(ax, 6, 50, 44, 6.5, "", fc="#FEF2F2", ec=RED, lw=1.8)
    txt(ax, 28, 53.2, "常见 Agent 的坑", fs=13, color="#B91C1C", weight="bold")
    box(ax, 60, 50, 44, 6.5, "", fc="#F0FDF4", ec=GREEN, lw=1.8)
    txt(ax, 82, 53.2, "LFL 的做法", fs=13, color="#047857", weight="bold")
    rows_l = [("声称完成", "'已经改好了'——其实命令没跑过"),
              ("参数靠猜", "路径 / 版本 / 状态全凭训练记忆想象"),
              ("失败静默", "重试吞掉报错，最后照样给出答案")]
    rows_r = [("回执文化", "未获 [状态: success] 回执，不声称完成"),
              ("先取证后判断", "训练先验只是假设，工具回执才是事实"),
              ("证据可复核", "结论绑定 EvidenceRef，随时回放原文")]
    for x, rows, ec, tc in [(6, rows_l, "#FCA5A5", "#B91C1C"), (60, rows_r, "#6EE7B7", "#047857")]:
        y = 36
        for head, body in rows:
            box(ax, x, y, 44, 10, "", fc="white", ec=ec, lw=1.6)
            txt(ax, x + 3, y + 6.8, head, fs=12, color=tc, weight="bold", ha="left")
            txt(ax, x + 3, y + 2.9, body, fs=9.6, color=INK, ha="left")
            if y > 12:
                arrow(ax, (x + 22, y - 0.5), (x + 22, y - 3.2), color="#CBD5E1", lw=1.8)
            y -= 13
    ax.add_patch(Circle((55, 31), 4.6, fc=NAVY, zorder=4))
    txt(ax, 55, 31, "VS", fs=14, color="white", weight="bold", zorder=5)
    save(fig, "img4_honesty.png")

# ---------- 5 evolution ----------
def evolution():
    fig, ax = new_fig(11, 6.2)
    title(ax, "自主演进闭环：AI 提案 → 人工放行 → 全程留痕")
    cx, cy, R = 35, 28, 17.5
    nodes = [("自我评估", "self_evaluate", BLUE),
             ("演进建议", "submit_evolution", CYAN),
             ("人工审阅", "审阅 / 授权 exec 级", AMBER),
             ("分级执行", "0/1/2 级权限落地", GREEN),
             ("全链路审计", "evolution_exec_log", PURPLE)]
    pts = []
    for i in range(5):
        ang = math.radians(90 - 72 * i)
        pts.append((cx + R * math.cos(ang), cy + R * math.sin(ang)))
    w, h = 18.5, 8
    for (px, py), (name, sub, col) in zip(pts, nodes):
        box(ax, px - w / 2, py - h / 2, w, h, "", fc="white", ec=col, lw=2.2, radius=1.3)
        txt(ax, px, py + 1.9, name, fs=12.5, color=col, weight="bold")
        txt(ax, px, py - 2.1, sub, fs=8.8, color=GRAY)
    for i in range(5):
        p1 = np.array(pts[i]); p2 = np.array(pts[(i + 1) % 5])
        u = (p2 - p1) / np.linalg.norm(p2 - p1)
        off = math.sqrt((w / 2 * u[0]) ** 2 + (h / 2 * u[1]) ** 2) + 1.3
        arrow(ax, tuple(p1 + u * off), tuple(p2 - u * off), color="#94A3B8", lw=2.0, rad=0.26)
    txt(ax, cx, cy + 2.5, "演进闭环", fs=13.5, color=NAVY, weight="bold")
    txt(ax, cx, cy - 2.2, "规则库是唯一真值源\ndocs/ai_rules.md", fs=9, color=GRAY)
    box(ax, 72, 6.5, 34, 44, "", fc="#F8FAFC", ec="#CBD5E1", lw=1.2)
    txt(ax, 89, 46.5, "真实运行数据（本工作区）", fs=12, color=NAVY, weight="bold")
    stats = [("184 条", "演进建议累计", BLUE), ("114 条", "已执行落地", GREEN),
             ("46 条", "审阅接受", CYAN), ("v19", "规则库版本", AMBER)]
    y = 40
    for num, label, col in stats:
        txt(ax, 78, y, num, fs=17, color=col, weight="bold", ha="left")
        txt(ax, 101.5, y, label, fs=10, color=GRAY, ha="right")
        y -= 8.0
    txt(ax, 89, 9.8, "来源：architecture_status 运行时回执\n（采集于 2026-10-14）", fs=8.2, color=GRAY)
    save(fig, "img5_evolution.png")

# ---------- 6 memory ----------
def memory():
    fig, ax = new_fig(11, 6.2)
    title(ax, "记忆不丢：从热上下文到长期经验的分层")
    layers = [
        (43, "#DBEAFE", "#2563EB", "HOT · 热上下文", "当前对话窗口：正在处理的消息与证据"),
        (32, "#E0F2FE", "#0891B2", "WARM · 压缩档案", "上下文超限自动另存分片，不静默丢弃"),
        (21, "#F1F5F9", "#64748B", "COLD · EvidenceRef", "稳定证据引用：可按 ref 精确回放原文"),
        (10, "#FEF9C3", "#CA8A04", "长期 · 经验 / 方法 / 规则", "experience / method / ai_rules.md 跨会话生效"),
    ]
    for y, fc, ec, head, body in layers:
        box(ax, 8, y, 52, 9, "", fc=fc, ec=ec, lw=1.8)
        txt(ax, 12, y + 5.8, head, fs=12, color=ec, weight="bold", ha="left")
        txt(ax, 12, y + 2.3, body, fs=9.5, color=INK, ha="left")
    arrow(ax, (64, 49), (64, 12), color="#94A3B8", lw=2.4)
    txt(ax, 66.5, 30, "沉淀", fs=11, color=GRAY, rotation=-90)
    arrow(ax, (72, 12), (72, 49), color=BLUE, lw=2.4)
    txt(ax, 75, 30, "检索", fs=11, color=BLUE, rotation=90)
    box(ax, 80, 30, 27, 20, "", fc="#F8FAFC", ec="#CBD5E1", lw=1.2)
    txt(ax, 93.5, 46, "事件溯源", fs=12, color=NAVY, weight="bold")
    txt(ax, 93.5, 38, "data/event_logs/<sid>.jsonl\n单一真相源\n可 replay / verify / fork", fs=9.2, color=INK)
    box(ax, 80, 8, 27, 18, "", fc="#F8FAFC", ec="#CBD5E1", lw=1.2)
    txt(ax, 93.5, 22.5, "反思蒸馏", fs=12, color=NAVY, weight="bold")
    txt(ax, 93.5, 15.5, "run 结束自动复盘\n经验 / 方法候选\n带真实出处入库", fs=9.2, color=INK)
    save(fig, "img6_memory.png")

# ---------- 7 capabilities ----------
def capabilities():
    fig, ax = new_fig(11, 6.6, (0, 110), (0, 66))
    title(ax, "能力全景：从'会聊天'到'能上手干活'", y=62)
    cards = [
        ("浏览器感知与操作", "只读 snapshot + 单派发 mutation\nCDP 接管真实 Chromium", BLUE),
        ("子代理与编排", "spawn / workflow / fix_loop\n租约预算与结果结算", CYAN),
        ("服务生命周期", "status / publish / restart\n发布绑定产物 hash 与 CAS", GREEN),
        ("模型体系", "目录 / 自主切换 / 应急降级链\n成本档位透明", PURPLE),
        ("评测体系", "固定场景集 + Wilson 区间\nnightly 自动跑", AMBER),
        ("蒸馏数据导出", "会话轨迹 → ReAct JSONL\n可复训自己的模型", "#D946EF"),
        ("MCP 只读导出", "经验 / 方法 / 证据接出\n接入任意 MCP 宿主", "#EA580C"),
        ("插件化 Skill", "SKILL.md 声明即扩展\n零代码接入工作流", "#0D9488"),
    ]
    xs = [5, 31.5, 58, 84.5]
    ys = [33, 7]
    for i, (head, body, col) in enumerate(cards):
        x = xs[i % 4]; y = ys[i // 4]
        box(ax, x, y, 23, 22, "", fc="white", ec="#E2E8F0", lw=1.4)
        ax.add_patch(Rectangle((x, y + 18.5), 23, 3.5, fc=col, ec="none", zorder=3))
        txt(ax, x + 11.5, y + 14.6, head, fs=11.8, color=col, weight="bold", zorder=5)
        txt(ax, x + 11.5, y + 7.2, body, fs=9.2, color=INK, zorder=5)
    save(fig, "img7_capabilities.png")

if __name__ == "__main__":
    banner(); positioning(); core_loop(); three_layers(); honesty(); evolution(); memory(); capabilities()
    print("ALL DONE")
