#!/usr/bin/env python3
"""dot 架构图 PNG 后期叠加工具 —— 虚线标注框 + 底部图例。

背景（2026-08-20 实战沉淀）:
  Graphviz cluster 画"某几个自然人是一致行动人"的虚线框时，与 rank 约束冲突会被静默丢弃
  （warning: already in a rankset, deleted from cluster）。与其跟 dot 纠缠，不如：
  ① 用不带 cluster 的干净布局渲染（0 交叉）；
  ② 用本工具按 `dot -Tplain` 输出的精确坐标，把虚线框/文字标注/图例叠加到 PNG 上。

用法（三步）:
  # 1. 渲染（-Gpad 给画布留边，避免标注框裁切）
  dot -Tplain -Gpad=1.2 graph.dot > graph.plain
  dot -Tpng -Gdpi=200 -Gpad=1.2 graph.dot -o graph.png

  # 2. 叠加虚线框（框住指定节点）+ 图例
  .venv/bin/python scripts/graphviz_overlay.py graph.png graph.plain out.png \
      --box-nodes ZHAO YANG LI \
      --box-label "一致行动人协议（赵/李/杨，锁定36个月）" \
      --legend "#D8E4F0:自然人 #3E5C8A:公司 #EDE3F5:合伙 #4F8A3C:目标 #F0F0F0:子公司"

  # 3. 若不想看图例：去掉 --legend 即可。

注意事项:
  - --pad 必须与渲染时的 -Gpad 一致（默认 1.2），否则坐标偏移。
  - plain 坐标原点在左下、y 向上；本工具内部已换算为 PNG 的左上原点。
  - 中文标注依赖系统字体，可用 --font 指定（默认 Hiragino Sans GB）。
"""
import argparse
import math
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

DEFAULT_FONT = '/System/Library/Fonts/Hiragino Sans GB.ttc'
FALLBACK_FONTS = [
    '/System/Library/Fonts/Hiragino Sans GB.ttc',
    '/System/Library/Fonts/STHeiti Medium.ttc',
    '/System/Library/Fonts/PingFang.ttc',
]


def pick_font(preferred):
    for p in ([preferred] if preferred else []) + FALLBACK_FONTS:
        if p and os.path.exists(p):
            return p
    return None


def parse_plain(fn):
    nodes, gh = {}, None
    with open(fn, encoding='utf-8') as f:
        lines = f.readlines()
    for line in lines:
        p = line.split()
        if not p:
            continue
        if p[0] == 'graph':
            gh = float(p[3])
        elif p[0] == 'node':
            nodes[p[1]] = (float(p[2]), float(p[3]), float(p[4]), float(p[5]))
    return nodes, gh


def main():
    ap = argparse.ArgumentParser(description='dot 架构图 PNG 叠加虚线框与图例')
    ap.add_argument('png_in')
    ap.add_argument('plain')
    ap.add_argument('png_out')
    ap.add_argument('--box-nodes', nargs='+', default=[], help='要框住的节点名（如 ZHAO YANG LI）')
    ap.add_argument('--box-label', default='', help='虚线框标注文字')
    ap.add_argument('--legend', default='', help='图例，格式 "颜色:文字 颜色:文字 ..."')
    ap.add_argument('--pad', type=float, default=1.2, help='与渲染时 -Gpad 一致（默认 1.2）')
    ap.add_argument('--dpi', type=int, default=200, help='渲染 DPI（默认 200）')
    ap.add_argument('--font', default='', help='标注字体路径（默认 Hiragino Sans GB）')
    args = ap.parse_args()

    nodes, gh = parse_plain(args.plain)
    img = Image.open(args.png_in).convert('RGBA')
    w, h = img.size
    sx = args.dpi  # px/inch
    font_path = pick_font(args.font)
    if not font_path:
        print('警告: 未找到中文字体，标注可能为方块', file=sys.stderr)

    def to_px(x_in, y_in):
        return (x_in + args.pad) * sx, (gh + args.pad - y_in) * sx

    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    if font_path:
        font = ImageFont.truetype(font_path, 21)
        font_small = ImageFont.truetype(font_path, 17)
    else:
        font = font_small = ImageFont.load_default()

    # ---- 虚线框 ----
    if args.box_nodes:
        xs, ys = [], []
        for n in args.box_nodes:
            if n not in nodes:
                print(f'警告: plain 输出中无节点 {n}', file=sys.stderr)
                continue
            x, y, w, h = nodes[n]
            xs += [x - w / 2, x + w / 2]
            ys += [y - h / 2, y + h / 2]
        if xs:
            pad_in = 0.24
            x0, y0 = to_px(min(xs) - pad_in, min(ys) - pad_in)
            x1, y1 = to_px(max(xs) + pad_in, max(ys) + pad_in)
            color = (192, 128, 58, 255)  # #C0803A 金色虚线

            def dash_line(p0, p1, dash=12, gap=7):
                dx, dy = p1[0] - p0[0], p1[1] - p0[1]
                dist = math.hypot(dx, dy)
                if dist == 0:
                    return
                ux, uy = dx / dist, dy / dist
                t = 0.0
                while t < dist:
                    t2 = min(t + dash, dist)
                    d.line([(p0[0] + ux * t, p0[1] + uy * t),
                            (p0[0] + ux * t2, p0[1] + uy * t2)], fill=color, width=2)
                    t = t2 + gap

            dash_line((x0, y0), (x1, y0))
            dash_line((x1, y0), (x1, y1))
            dash_line((x1, y1), (x0, y1))
            dash_line((x0, y1), (x0, y0))
            if args.box_label:
                d.text((x0 + 10, y1 + 8), args.box_label, fill=color, font=font)  # y1=框顶

    # ---- 图例 ----
    if args.legend:
        lh = 48
        ly = h - lh - 8
        leg = Image.new('RGBA', img.size, (0, 0, 0, 0))
        dl = ImageDraw.Draw(leg)
        dl.rectangle([12, ly, w - 12, h - 8], fill=(250, 250, 250, 235), outline=(200, 200, 200, 255))
        items = [seg.strip() for seg in re.split(r'\s+', args.legend) if seg.strip()]
        x = 32
        for item in items:
            if ':' not in item:
                continue
            color_str, txt = item.split(':', 1)
            color = tuple(int(color_str.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4)) + (255,)
            dl.rounded_rectangle([x, ly + 13, x + 22, ly + 35], radius=4, fill=color,
                                 outline=(120, 120, 120, 255), width=1)
            dl.text((x + 29, ly + 13), txt, fill=(60, 60, 60, 255), font=font_small)
            x += 29 + dl.textlength(txt, font=font_small) + 28
        dl.text((x + 8, ly + 13), '实线=持股   虚线=GP管理权', fill=(60, 60, 60, 255), font=font_small)
        img = Image.alpha_composite(img, leg)

    img = Image.alpha_composite(img, overlay)
    img.convert('RGB').save(args.png_out)
    print(f'叠加完成 -> {args.png_out}')


if __name__ == '__main__':
    sys.exit(main())
