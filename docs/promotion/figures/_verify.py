# -*- coding: utf-8 -*-
"""像素级自检：检测内容是否越出画布/色块，以及文字与色块底边的间距。"""
import sys
from PIL import Image

def analyze(path):
    im = Image.open(path).convert("RGB")
    W, H = im.size
    px = im.load()
    BG = (255, 255, 255)
    def is_bg(c):
        return abs(c[0]-BG[0]) < 6 and abs(c[1]-BG[1]) < 6 and abs(c[2]-BG[2]) < 6
    # 全画布非背景内容包围盒
    minx, miny, maxx, maxy = W, H, -1, -1
    for y in range(H):
        for x in range(W):
            if not is_bg(px[x, y]):
                if x < minx: minx = x
                if y < miny: miny = y
                if x > maxx: maxx = x
                if y > maxy: maxy = y
    print(f"{path}  size={W}x{H}")
    print(f"  content bbox: x[{minx},{maxx}] y[{miny},{maxy}]")
    print(f"  bottom margin: {H-1-maxy}px   right margin: {W-1-maxx}px")
    return im, px, W, H, is_bg

def block_bottom_margin(path, box, label):
    """box=(x0,y0,x1,y1) 统计该色块内非背景像素最低点距色块底边的距离"""
    im, px, W, H, is_bg = analyze(path)
    x0, y0, x1, y1 = box
    maxy = -1
    for y in range(y0, y1):
        for x in range(x0, x1):
            if not is_bg(px[x, y]):
                if y > maxy: maxy = y
    print(f"  [{label}] box y[{y0},{y1}]  inner content max y={maxy}  margin={y1-maxy}px")

if __name__ == "__main__":
    analyze(sys.argv[1])
