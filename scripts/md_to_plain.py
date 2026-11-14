#!/usr/bin/env python3
"""把 Markdown 稿件转成知乎可见正文等价的纯文本发布版。

动机：Host 的 article_publish 准入要求「稿件正文行与页面可见正文一致」。
知乎富文本编辑器不解析粘贴的 Markdown 符号，若直接插入 Markdown 源码，
读者会看到 **、#、| 等标记。因此统一落盘一份「阅读友好纯文本版」：
  - 同一份文件既是稿件（审读材料 + SHA 指纹）又是页面正文，二者逐行一致。
规则：
  - 去掉 ** __ 行内强调标记，保留文字本身
  - 去掉 # 前缀（标题文字保留）
  - 引用行 > x  → 「x」独占一行
  - 表格 | a | b | → 「- a：b」逐行展开
  - --- 分隔线 → 空行
"""
from __future__ import annotations

import re
import sys


def convert(md: str) -> str:
    out: list[str] = []
    lines = md.split("\n")
    table_header: list[str] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        if re.fullmatch(r"-{3,}", line.strip()):
            out.append("")
            i += 1
            continue
        s = line.strip()
        if not s.startswith("|"):
            table_header = []
        # 表格行
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            is_sep = all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells)
            if is_sep:
                # 分隔行：表头已在其上一行处理，此处只跳过
                i += 1
                continue
            cells = [c for c in cells if c]
            cells = [re.sub(r"\*\*(.+?)\*\*", r"\1", c) for c in cells]
            cells = [re.sub(r"`(.+?)`", r"\1", c) for c in cells]
            if len(cells) >= 2:
                if not table_header:
                    table_header = cells
                    out.append("（下表列名依次为：" + "｜".join(cells) + "）")
                    out.append("")
                    i += 1
                    continue
                pairs = []
                for idx, val in enumerate(cells):
                    head = table_header[idx] if idx < len(table_header) else ""
                    pairs.append(f"{head}：{val}" if head else val)
                out.append("｜".join(pairs))
            else:
                out.append("「" + (cells[0] if cells else "") + "」")
            i += 1
            continue
        # 标题
        s = re.sub(r"^#{1,6}\s*", "", s)
        # 引用：Markdown blockquote（> 开头）→ 「...」独占一行
        if line.lstrip().startswith(">"):
            q = re.sub(r"^\s*>\s?", "", line)
            q = re.sub(r"\*\*(.+?)\*\*", r"\1", q)
            q = re.sub(r"`(.+?)`", r"\1", q)
            q = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", q)
            if q.strip():
                out.append("「" + q.strip() + "」")
            i += 1
            continue
        # 行内强调
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"`(.+?)`", r"\1", s)
        s = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", s)
        out.append(s)
        i += 1
    # 折叠连续空行到最多 1 个，保留段落分隔
    res: list[str] = []
    blank = False
    for ln in out:
        if not ln.strip():
            blank = True
            continue
        if blank and res:
            res.append("")
        blank = False
        res.append(ln)
    return "\n".join(res).strip() + "\n"


if __name__ == "__main__":
    src = sys.argv[1]
    dst = sys.argv[2]
    with open(src, encoding="utf-8") as f:
        md = f.read()
    text = convert(md)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {dst}: {len(text)} chars, {len(text.splitlines())} lines")
