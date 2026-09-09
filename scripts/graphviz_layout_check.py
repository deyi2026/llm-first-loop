#!/usr/bin/env python3
"""Graphviz(dot) 架构图布局质量分析器 —— 用 plain 输出做客观几何检测。

背景（2026-08-20 实战沉淀）:
  股权架构图初次渲染有 3 处连线交叉、cluster 与 rank 约束冲突导致"一致行动人"框被丢弃。
  肉眼检查不可靠（尤其大图），改用 `dot -Tplain` 输出全部节点包围盒与连线折线，
  逐段做线段相交检测，量化 交叉数 / 节点重叠 / 连线穿过无关节点 三个指标。

用法:
  # 直接分析 .dot 文件（内部先转 plain）
  .venv/bin/python scripts/graphviz_layout_check.py target.dot

  # 或分析已有的 plain 输出
  dot -Tplain target.dot > target.plain
  .venv/bin/python scripts/graphviz_layout_check.py --plain target.plain

  # 只统计可见边（忽略 style=invis 保序边），默认即此行为
输出:
  - 可见边交叉数及交叉边对（重点指标，目标 0）
  - 节点-节点重叠
  - 连线穿过无关节点包围盒（≥2 个点落入即计）

排障指引（本工具曾用到的 dot 布局坑）:
  1. 长跨层直连边（如自然人→目标公司）是交叉主因 → 调整同层节点顺序，或用
     {rank=same; ...} + 隐形保序边 `A -> B [style=invis, weight=100]` 固定左右顺序。
  2. 节点同时进 graph 级 rank=same 与 cluster → 会被移出 cluster（warning: already in a rankset）。
     解法：cluster 内放 {rank=same; ...}，或 graph 级 newrank=true，或外层无框 cluster 嵌套内层画框 cluster。
  3. 隐形边横跨两个 rank 组会把两组顶开 → 对纯保序用途加 [style=invis, weight=100, constraint=false]。
"""

import argparse
import os
import subprocess
import sys
import tempfile


def parse_plain(fn):
    """解析 dot -Tplain 输出：nodes[name]=(x,y,w,h)；edges=[(src,dst,pts,style)]"""
    nodes, edges = {}, []
    with open(fn, encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines:
        p = line.split()
        if not p:
            continue
        if p[0] == "node":
            nodes[p[1]] = tuple(map(float, p[2:6]))
        elif p[0] == "edge":
            npts = int(p[3])
            pts = []
            i = 4
            for _ in range(npts):
                pts.append((float(p[i]), float(p[i + 1])))
                i += 2
            rest = p[i:]
            style = "invis" if "invis" in rest else ""
            edges.append((p[1], p[2], pts, style))
    return nodes, edges


def seg_intersect(a, b, c, d):
    """线段 ab 与 cd 是否真正相交（不含共线退化）。"""

    def ccw(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1, o2 = ccw(a, b, c), ccw(a, b, d)
    o3, o4 = ccw(c, d, a), ccw(c, d, b)
    return o1 * o2 < 0 and o3 * o4 < 0


def on_bbox(p, bb, pad=0.02):
    x, y, w, h = bb
    return x - w / 2 - pad <= p[0] <= x + w / 2 + pad and y - h / 2 - pad <= p[1] <= y + h / 2 + pad


def analyze(fn):
    nodes, edges = parse_plain(fn)
    vis = [(s, d, pts) for (s, d, pts, st) in edges if st != "invis"]
    print(f"### {fn}  节点={len(nodes)} 边={len(edges)} 可见边={len(vis)}")

    # 1) 节点-节点重叠
    names = list(nodes)
    ov = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = nodes[names[i]], nodes[names[j]]
            if abs(a[0] - b[0]) < (a[2] + b[2]) / 2 and abs(a[1] - b[1]) < (a[3] + b[3]) / 2:
                ov.append((names[i], names[j]))
    print("  节点重叠:", ov if ov else "无")

    # 2) 可见边交叉（共点边跳过）
    cross, pairs = 0, []
    for i in range(len(vis)):
        for j in range(i + 1, len(vis)):
            ea, eb = vis[i], vis[j]
            if ea[0] in (eb[0], eb[1]) and ea[1] in (eb[0], eb[1]):
                continue
            hit = False
            for k in range(len(ea[2]) - 1):
                for m in range(len(eb[2]) - 1):
                    if seg_intersect(ea[2][k], ea[2][k + 1], eb[2][m], eb[2][m + 1]):
                        cross += 1
                        pairs.append((ea[0] + "->" + ea[1], eb[0] + "->" + eb[1]))
                        hit = True
                        break
                if hit:
                    break
    print(f"  可见边交叉: {cross}  ← 目标为 0")
    for a, b in pairs[:12]:
        print(f"    {a} × {b}")

    # 3) 连线穿过无关节点
    through = []
    for src, dst, pts, st in edges:
        if st == "invis":
            continue
        for nname, bb in nodes.items():
            if nname in (src, dst):
                continue
            if sum(1 for pt in pts if on_bbox(pt, bb)) >= 2:
                through.append((src + "->" + dst, nname))
    print("  穿过节点:", through[:12] if through else "无")

    return cross


def main():
    ap = argparse.ArgumentParser(description="dot 架构图布局质量分析（交叉/重叠/穿过）")
    ap.add_argument("input", help=".dot 文件 或 --plain 时的 plain 输出文件")
    ap.add_argument("--plain", action="store_true", help="输入已是 dot -Tplain 输出")
    args = ap.parse_args()

    if args.plain:
        analyze(args.input)
        return 0

    # 直接对 .dot 分析：转 plain（临时文件）
    fd, tmp = tempfile.mkstemp(suffix=".plain")
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            r = subprocess.run(
                ["dot", "-Tplain", args.input], stdout=fh, stderr=subprocess.PIPE, text=True
            )
        if r.returncode != 0:
            print("dot 渲染失败:", r.stderr, file=sys.stderr)
            return 1
        analyze(tmp)
    finally:
        os.unlink(tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
