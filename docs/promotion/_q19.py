import zh2, json, re
tab = zh2.pick("/edit"); zh2.activate(tab)
# --- content integrity ---
ed = zh2.ev(tab, "document.querySelector('.public-DraftEditor-content').innerText")
src = open("20261010-lfl-daily-03.md", encoding="utf-8").read().split("\n",1)[1]
def norm(s):
    s = re.sub(r'```[a-z]*', '', s)
    s = re.sub(r'^\s*[#>\-\d.]+\s*', '', s, flags=re.M)
    s = s.replace('**','').replace('`','')
    s = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', s)
    return re.sub(r'\s', '', s)
a, b = norm(ed), norm(src)
print("editor_norm:", len(a), "src_norm:", len(b))
print("missing_in_editor:", len(b) - len(a))
# find first divergence
i = 0
while i < min(len(a), len(b)) and a[i] == b[i]: i += 1
print("first_diff_at:", i)
print("  editor:", a[i:i+60])
print("  source:", b[i:i+60])
# --- strong/code spans ---
print("styled:", zh2.ev(tab, r"""(()=>{const h=document.querySelector('.public-DraftEditor-content');
 return JSON.stringify({bold:h.querySelectorAll('[style*="font-weight"]').length,
  mono:h.querySelectorAll('[style*="Menlo"]').length,
  h2:h.querySelectorAll('h2').length, pre:h.querySelectorAll('pre').length});})()"""))
