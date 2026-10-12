import zh2, json
tab = zh2.pick("/edit"); zh2.activate(tab)
zh2.click(tab, "document.querySelector('.public-DraftEditor-content')")
print("selectAll cmd:", zh2.cmd_key(tab, "a", "KeyA", 65, ["selectAll"]))
print("selText len:", zh2.ev(tab, "window.getSelection().toString().length"))
print("cut:", zh2.cmd_key(tab, "x", "KeyX", 88, ["cut"]))
print("counter:", zh2.counter(tab))
print("paste:", zh2.cmd_key(tab, "v", "KeyV", 86, ["paste"], wait=5.0))
print("counter:", zh2.counter(tab))
print("structure:", zh2.ev(tab, r"""(()=>{const h=document.querySelector('.public-DraftEditor-content');
 const c={}; [...h.querySelectorAll('h1,h2,h3,p,ul,ol,li,pre,blockquote,strong,table,img')].forEach(e=>c[e.tagName.toLowerCase()]=(c[e.tagName.toLowerCase()]||0)+1);
 return JSON.stringify(c);})()"""))
