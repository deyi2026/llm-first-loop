# -*- coding: utf-8 -*-
import os
from PIL import Image, ImageDraw, ImageFont

W = 1000
BG = (255, 255, 255)
INK = (28, 33, 41)
MUTE = (114, 122, 134)
LINE = (223, 227, 231)
NAVY = (23, 55, 88)
ACCENT = (198, 68, 26)
ACC2 = (30, 106, 163)
ACC3 = (25, 135, 84)
SOFT = (246, 248, 250)

F_M = "/System/Library/Fonts/STHeiti Medium.ttc"
F_L = "/System/Library/Fonts/STHeiti Light.ttc"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "img")

def f(size, medium=True):
    return ImageFont.truetype(F_M if medium else F_L, size)

def wrap(s, font, maxw):
    lines, cur = [], ""
    for ch in s:
        if ch == "\n":
            lines.append(cur); cur = ""; continue
        if cur and font.getlength(cur + ch) > maxw:
            lines.append(cur); cur = ch
        else:
            cur += ch
    if cur: lines.append(cur)
    return lines

def block(d, x, y, s, font, maxw, fill=INK, lh=1.6):
    for ln in wrap(s, font, maxw):
        d.text((x, y), ln, font=font, fill=fill)
        y += int(font.size * lh)
    return y

def canvas(title, sub, h):
    img = Image.new("RGB", (W, h), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([(52, 50), (60, 50 + 54)], fill=ACCENT)
    d.text((80, 44), title, font=f(38), fill=INK)
    d.text((80, 100), sub, font=f(21), fill=MUTE)
    d.line([(52, 142), (W - 52, 142)], fill=LINE, width=2)
    return img, d

def save(img, name):
    p = os.path.join(OUT, name)
    os.makedirs(OUT, exist_ok=True)
    img.save(p, "PNG")
    print("saved", p, img.size)
