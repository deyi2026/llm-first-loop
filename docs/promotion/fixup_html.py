# -*- coding: utf-8 -*-
"""md2html.py 输出后的头条适配后处理（可复用）。
1) <h1> 会被头条塌缩成一级标题 -> 改写为 <p><strong>
2) 图片行经 link-stripping 后残留裸 '!' -> 去掉
"""
import re, sys

def fixup(h):
    h = re.sub(r'<h1>(.*?)</h1>', r'<p><strong>\1</strong></p>', h)
    h = re.sub(r'<p>\s*!([^<]{0,120}?)</p>', r'<p>\1</p>', h)
    return h

if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    h = fixup(open(src, encoding="utf-8").read())
    open(dst, "w", encoding="utf-8").write(h)
    print("h1:", h.count("<h1"), "| p:", h.count("<p>"),
          "| 裸!图注:", len(re.findall(r'<p>\s*!', h)))
