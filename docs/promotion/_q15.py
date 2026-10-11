import zh2, json
tab = zh2.pick("/edit"); zh2.activate(tab)
zh2.click(tab, "document.querySelector('.public-DraftEditor-content')")
zh2.ev(tab, """(()=>{const ed=document.querySelector('.public-DraftEditor-content');
 const s=window.getSelection(); const r=document.createRange(); r.selectNodeContents(ed);
 s.removeAllRanges(); s.addRange(r); return 1;})()""")
zh2.key(tab, "Backspace", wait=0.8)
probe = ("1. 有序一\n\n2. 有序二\n\n---\n\n```bash\necho hi\n```\n\n"
         "| 维度 | A | B |\n|---|---|---|\n| x | 1 | 2 |")
print("type:", zh2.type_md(tab, probe, wait=2.5))
print("counter:", zh2.counter(tab))
print("html:", zh2.ev(tab, r"""(()=>{const h=document.querySelector('.public-DraftEditor-content');
 return JSON.stringify([...h.children].map(c=>c.tagName+':'+((c.innerText||'').replace(/\s+/g,' ').slice(0,28))));})()"""))
