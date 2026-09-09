#!/usr/bin/env python3
"""md → PDF 渲染器（reportlab，支持中文、表格、图片、多级标题、加粗、引用块、页码）。

用法:
  .venv/bin/python scripts/md2pdf.py <in.md> <out.pdf> [--title "..."] [--no-images] [--image-filter 关键词]

升级说明（2026-08-20，实战沉淀）:
  旧版只支持 # / ## 标题、表格、列表、引用，缺：### 三级标题、**加粗**、图片嵌入、页码、表格美化。
  新版补全这些能力；图片以压缩 PNG 单次嵌入（此前有报告把图以裸 RGBA 存两份 → 6.8MB，改后 300KB 级）。
"""

import argparse
import os
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# 注册 CJK 字体（中文支持，STSong-Light 为 reportlab 内置 CID 字体）
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

# ---------- 样式 ----------
C_PRIMARY = colors.HexColor("#1F3B5C")  # 深蓝（标题）
C_ACCENT = colors.HexColor("#2E6DA4")  # 中蓝（表头/三级标题）
C_GREY = colors.HexColor("#666666")
C_BORDER = colors.HexColor("#B8C4D0")


def build_styles():
    s = {}
    s["h1"] = ParagraphStyle(
        "h1",
        fontName="STSong-Light",
        fontSize=17,
        leading=24,
        textColor=C_PRIMARY,
        spaceBefore=4,
        spaceAfter=10,
    )
    s["h2"] = ParagraphStyle(
        "h2",
        fontName="STSong-Light",
        fontSize=13.5,
        leading=19,
        textColor=C_PRIMARY,
        spaceBefore=10,
        spaceAfter=6,
    )
    s["h3"] = ParagraphStyle(
        "h3",
        fontName="STSong-Light",
        fontSize=11.5,
        leading=16,
        textColor=C_ACCENT,
        spaceBefore=8,
        spaceAfter=4,
    )
    s["body"] = ParagraphStyle(
        "body",
        fontName="STSong-Light",
        fontSize=10,
        leading=15.5,
        textColor=colors.HexColor("#222222"),
        spaceAfter=4,
    )
    s["quote"] = ParagraphStyle(
        "quote", parent=s["body"], leftIndent=10, fontSize=9.5, leading=14.5, textColor=C_GREY
    )
    s["bullet"] = ParagraphStyle("bullet", parent=s["body"], leftIndent=12, bulletIndent=2)
    s["caption"] = ParagraphStyle(
        "caption",
        fontName="STSong-Light",
        fontSize=9,
        leading=13,
        textColor=C_GREY,
        alignment=1,
        spaceBefore=4,
        spaceAfter=8,
    )
    return s


# ---------- Markdown 内联解析 ----------
def inline(text):
    """处理 **加粗**（& < > 先转义防注入）。"""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return text


# ---------- 表格 ----------
def render_table(rows, styles):
    """rows: list of list[str]（含表头）"""
    header = rows[0]
    cell_style = ParagraphStyle("cell", fontName="STSong-Light", fontSize=9.5, leading=13.5)
    head_style = ParagraphStyle("head", parent=cell_style, textColor=colors.white)
    tdata = [[Paragraph(inline(h), head_style) for h in header]]
    for r in rows[1:]:
        tdata.append([Paragraph(inline(c), cell_style) for c in r])
    ncols = len(header)
    usable = 180 * mm
    col_w = [usable / ncols] * ncols
    t = Table(tdata, colWidths=col_w, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), C_ACCENT),
                ("GRID", (0, 0), (-1, -1), 0.5, C_BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F8FC")]),
            ]
        )
    )
    return t


# ---------- 主流程 ----------
def md2pdf(md_path, pdf_path, no_images=False, title="", image_filter=None):
    """渲染 Markdown 到 PDF。image_filter：只嵌入文件名含该关键词的图片（用于多图报告出单图版本）。"""
    with open(md_path, encoding="utf-8") as f:
        md = f.read()
    base_dir = os.path.dirname(os.path.abspath(md_path))
    styles = build_styles()

    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=title or os.path.splitext(os.path.basename(md_path))[0],
    )

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("STSong-Light", 8)
        canvas.setFillColor(C_GREY)
        canvas.drawCentredString(A4[0] / 2, 9 * mm, f"— {doc_.page} —")
        canvas.restoreState()

    story = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 图片
        img_match = re.match(r"!\[(.*?)\]\((.+?)\)", stripped)
        if img_match and not no_images:
            cap, path = img_match.group(1), img_match.group(2)
            if image_filter and image_filter not in os.path.basename(path):
                i += 1
                continue
            p = path if os.path.isabs(path) else os.path.join(base_dir, path)
            if os.path.exists(p):
                try:
                    from reportlab.lib.utils import ImageReader

                    iw, ih = ImageReader(p).getSize()
                    max_w = 175 * mm
                    if iw > 0:
                        h = max_w * ih / iw
                        story.append(Spacer(1, 4))
                        story.append(Image(p, width=max_w, height=h))
                        if cap:
                            story.append(Paragraph(f"图：{cap}", styles["caption"]))
                        story.append(Spacer(1, 6))
                except Exception:
                    story.append(Paragraph(f"[图片加载失败: {p}]", styles["body"]))
            else:
                story.append(Paragraph(f"[图片缺失: {p}]", styles["body"]))
            i += 1
            continue

        # 标题
        if stripped.startswith("# "):
            story.append(Paragraph(inline(stripped[2:]), styles["h1"]))
            story.append(Spacer(1, 2))
        elif stripped.startswith("## "):
            story.append(Paragraph(inline(stripped[3:]), styles["h2"]))
        elif stripped.startswith("### "):
            story.append(Paragraph(inline(stripped[4:]), styles["h3"]))
        # 引用
        elif stripped.startswith("> "):
            story.append(Paragraph(inline(stripped[2:]), styles["quote"]))
        # 表格
        elif (
            stripped.startswith("|")
            and i + 1 < len(lines)
            and re.match(r"^\|[\s:|-]+\|?$", lines[i + 1].strip())
        ):
            tbl = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tbl.append(lines[i].strip())
                i += 1
            rows = [[c.strip() for c in tline.strip("|").split("|")] for tline in tbl]
            if len(rows) >= 2:
                story.append(Spacer(1, 2))
                story.append(render_table(rows, styles))
                story.append(Spacer(1, 6))
            continue
        # 列表
        elif stripped.startswith("- ") or stripped.startswith("* "):
            story.append(Paragraph("• " + inline(stripped[2:]), styles["bullet"]))
        # 分割线
        elif stripped in ("---", "***", "___"):
            story.append(Spacer(1, 4))
            t = Table([[""]], colWidths=[180 * mm], rowHeights=[0.5])
            t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, C_BORDER)]))
            story.append(t)
            story.append(Spacer(1, 4))
        # 空行
        elif stripped == "":
            story.append(Spacer(1, 3))
        # 普通段落
        else:
            story.append(Paragraph(inline(stripped), styles["body"]))
        i += 1

    # 末尾分隔线
    story.append(Spacer(1, 4))
    t = Table([[""]], colWidths=[180 * mm], rowHeights=[0.5])
    t.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), 0.5, C_BORDER)]))
    story.append(t)

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(f"PDF 生成: {pdf_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Markdown → PDF（reportlab，中文/表格/图片/多级标题）")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--no-images", action="store_true", help="不嵌入图片（纯文字版）")
    ap.add_argument("--title", default="", help="PDF 元数据标题")
    ap.add_argument("--image-filter", default="", help="只嵌入文件名含该关键词的图片")
    args = ap.parse_args()
    md2pdf(
        args.input,
        args.output,
        no_images=args.no_images,
        title=args.title,
        image_filter=args.image_filter or None,
    )
