# -*- coding: utf-8 -*-
import re, html as H

def inline(s):
    s = H.escape(s, quote=False)
    s = s.replace('\\*', '\x00')                       # 转义星号先占位，避免被斜体规则吃掉
    s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
    s = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1', s)          # 链接被头条剥离，保留文字
    s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<strong>\1</strong>', s)
    s = s.replace('\x00', '*')                          # 还原为普通星号
    return s

def convert(md):
    out, i, lines = [], 0, md.split("\n")
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):                                  # 代码块
            i += 1; buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1
            out.append("<pre><code>" + H.escape("\n".join(buf)) + "</code></pre>")
            continue
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r'^\|[\s:|-]+\|$', lines[i+1].strip()):
            i += 2; rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")]); i += 1
            n = max(len(r) for r in rows)
            t = "<table>"
            for ri, r in enumerate(rows):
                tag = "td"
                cells = "".join("<%s>%s</%s>" % (tag, inline(c), tag) for c in r + [""] * (n - len(r)))
                t += "<tr>" + cells + "</tr>"
            out.append(t + "</table>")
            continue
        m = re.match(r'^(#{2,3})\s+(.*)$', ln)
        if m:
            txt = inline(m.group(2))
            out.append("<h1>%s</h1>" % txt if len(m.group(1)) == 2 else "<p><strong>%s</strong></p>" % txt)
            i += 1; continue
        if re.match(r'^(---|\*\*\*)\s*$', ln):
            out.append("<hr>"); i += 1; continue
        if ln.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(lines[i].lstrip(">").strip()); i += 1
            out.append("<blockquote><p>%s</p></blockquote>" % inline(" ".join(x for x in buf if x)))
            continue
        if re.match(r'^\s*[-*]\s+', ln):
            items = []
            while i < len(lines) and re.match(r'^\s*[-*]\s+', lines[i]):
                items.append("<li>%s</li>" % inline(re.sub(r'^\s*[-*]\s+', '', lines[i]))); i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        if re.match(r'^\s*\d+\.\s+', ln):
            items = []
            while i < len(lines) and re.match(r'^\s*\d+\.\s+', lines[i]):
                items.append("<li>%s</li>" % inline(re.sub(r'^\s*\d+\.\s+', '', lines[i]))); i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue
        if not ln.strip():
            i += 1; continue
        buf = []
        while i < len(lines) and lines[i].strip() and not re.match(r'^(#{1,3}\s|\s*[-*]\s|\s*\d+\.\s|>|\||```|---)', lines[i]):
            buf.append(lines[i].strip()); i += 1
        if buf:
            out.append("<p>%s</p>" % inline(" ".join(buf)))
    return "".join(out)

if __name__ == "__main__":
    import sys
    md = open(sys.argv[1], encoding="utf-8").read()
    body = md.split("\n", 1)[1]                       # 去掉 L1 标题行
    body = body.replace("**参考来源：**", "## 参考来源")
    h = convert(body)
    open(sys.argv[2], "w", encoding="utf-8").write(h)
    print("chars:", len(h))
    print("tags:", {t: h.count("<" + t) for t in ["h1", "p", "strong", "ul", "ol", "li", "table", "tr", "pre", "hr", "blockquote", "code"]})
