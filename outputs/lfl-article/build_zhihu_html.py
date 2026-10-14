# -*- coding: utf-8 -*-
"""zhihu-article.md -> zhihu-body-embed.html (data-URI images) for paste into zhuanlan editor."""
import base64, os, re, html as H
BASE = os.path.dirname(os.path.abspath(__file__))

def b64(p):
    with open(os.path.join(BASE, p), "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()

def inline(s):
    s = H.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\*(.+?)\*", r"<i>\1</i>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"\[(.+?)\]\((.+?)\)", r"<a href='\2'>\1</a>", s)
    return s

src = open(os.path.join(BASE, "zhihu-article.md"), encoding="utf-8").read()
out, in_code, code_buf, list_open = [], False, [], None
def close_list():
    global list_open
    if list_open:
        out.append("</ul>")
        list_open = False
for line in src.splitlines():
    st = line.strip()
    if st.startswith("```"):
        if in_code:
            out.append("<pre>" + H.escape("\n".join(code_buf), quote=False) + "</pre>")
            code_buf, in_code = [], False
        else:
            close_list(); in_code = True
        continue
    if in_code:
        code_buf.append(line); continue
    m = re.match(r"!\[(.*?)\]\((assets/[^)]+)\)", st)
    if m:
        close_list(); out.append(f'<p><img src="{b64(m.group(2))}" alt="{m.group(1)}"></p>'); continue
    if st.startswith("# "):
        continue  # title goes to editor title field
    if st.startswith("## "):
        close_list(); out.append("<h2>" + inline(st[3:]) + "</h2>"); continue
    if st.startswith("#"):
        close_list(); out.append("<h3>" + inline(st.lstrip("#").strip()) + "</h3>"); continue
    if st.startswith("- "):
        if not list_open:
            out.append("<ul>")
            list_open = True
        out.append("<li>" + inline(st[2:]) + "</li>")
        continue
    if st == "---":
        close_list(); out.append("<hr>"); continue
    if st.startswith("> "):
        close_list(); out.append("<blockquote>" + inline(st[2:]) + "</blockquote>"); continue
    if not st:
        close_list(); continue
    close_list(); out.append("<p>" + inline(st) + "</p>")
close_list()
html_text = "\n".join(out)
open(os.path.join(BASE, "zhihu-body-embed.html"), "w", encoding="utf-8").write(html_text)
print("zhihu-body-embed.html written:", len(html_text), "chars, imgs:", html_text.count("data:image/"))
