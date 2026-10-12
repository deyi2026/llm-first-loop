import zh2, json
tab = zh2.pick("/edit"); zh2.activate(tab)
zh2.click(tab, "document.querySelector('.public-DraftEditor-content')")
zh2.ev(tab, """(()=>{const ed=document.querySelector('.public-DraftEditor-content');
 const s=window.getSelection(); const r=document.createRange(); r.selectNodeContents(ed);
 s.removeAllRanges(); s.addRange(r); return 1;})()""")
zh2.key(tab, "Backspace", wait=0.8)
probe = "# 一级标题\n\n正文一句。\n\n## 二级标题\n\n> 引用一句。\n\n- 列表一\n- 列表二\n\n**加粗片段**与`行内代码`。"
print("type:", zh2.type_md(tab, probe, wait=2.5))
print("counter:", zh2.counter(tab))
print("html:", zh2.ev(tab, "document.querySelector('.public-DraftEditor-content').innerHTML"))
