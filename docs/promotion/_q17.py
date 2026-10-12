import zh2, json, subprocess
tab = zh2.pick("/edit"); zh2.activate(tab)
zh2.click(tab, "document.querySelector('.public-DraftEditor-content')")
zh2.ev(tab, """(()=>{const ed=document.querySelector('.public-DraftEditor-content');
 const s=window.getSelection(); const r=document.createRange(); r.selectNodeContents(ed);
 s.removeAllRanges(); s.addRange(r); return 1;})()""")
zh2.key(tab, "Backspace", wait=1.0)
print("cleared:", zh2.counter(tab))
print("paste:", zh2.key(tab, "V", mods=4, wait=4.0))
print("counter:", zh2.counter(tab))
print("structure:", zh2.ev(tab, r"""(()=>{const h=document.querySelector('.public-DraftEditor-content');
 const c={}; [...h.querySelectorAll('h1,h2,h3,p,ul,ol,li,pre,blockquote,strong,table,img')].forEach(e=>c[e.tagName.toLowerCase()]=(c[e.tagName.toLowerCase()]||0)+1);
 return JSON.stringify(c);})()"""))
