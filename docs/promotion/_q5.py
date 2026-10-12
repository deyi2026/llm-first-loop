import zh2, json
tab = zh2.pick("/edit"); zh2.activate(tab)
zh2.click(tab, "document.querySelector('.public-DraftEditor-content')")
zh2.ev(tab, """(()=>{const ed=document.querySelector('.public-DraftEditor-content');
 const s=window.getSelection(); const r=document.createRange(); r.selectNodeContents(ed);
 s.removeAllRanges(); s.addRange(r); return 1;})()""")
zh2.key(tab, "Backspace", wait=1.0)
print("CLEARED:", zh2.counter(tab))
print("click 导入 caret:", zh2.click(tab, "[...document.querySelectorAll('button')].find(b=>b.innerText.includes('导入')).querySelector('svg')"))
print("MENU:", zh2.ev(tab, r"""(()=>{const out=[];
 document.querySelectorAll('li,button,a,div').forEach(e=>{
   const r=e.getBoundingClientRect(); const txt=(e.innerText||'').replace(/\s+/g,' ').trim();
   if(r.width>0&&r.height>0&&r.height<50&&e.children.length===0&&txt&&txt.length<20)
     out.push({tag:e.tagName,txt,x:Math.round(r.left),y:Math.round(r.top)});});
 return JSON.stringify(out.filter(o=>o.y>80&&o.y<400),null,1);})()"""))
