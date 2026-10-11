import zh2, json
tab = zh2.pick("/edit"); zh2.activate(tab)
print("editor:", zh2.counter(tab))
print("struct:", zh2.ev(tab, r"""(()=>{const h=document.querySelector('.public-DraftEditor-content');
 const c={}; ['h2','h3','pre','blockquote','ul','li','img','table'].forEach(t=>c[t]=h.querySelectorAll(t).length);
 return JSON.stringify(c);})()"""))
print("bold/mono:", zh2.ev(tab, r"""(()=>{const h=document.querySelector('.public-DraftEditor-content');
 return JSON.stringify({bold:h.querySelectorAll('[style*="font-weight"]').length, mono:h.querySelectorAll('[style*="Menlo"]').length});})()"""))
print("footer:", zh2.ev(tab, r"""(()=>{const t=document.body.innerText;
 const m=t.match(/字数[：:]\s*\d+[\s\S]{0,40}/); const b=[...document.querySelectorAll('button')].filter(x=>['更新','发布'].includes(x.innerText.replace(/\s/g,'')));
 return JSON.stringify({near:m?m[0].replace(/\s+/g,' '):null, btns:b.map(x=>({t:x.innerText.replace(/\s/g,''),d:x.disabled}))});})()"""))
