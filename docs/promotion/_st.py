import zh2, json, time
tab = zh2.pick("/edit"); zh2.activate(tab)
print("counter:", zh2.counter(tab))
print("img positions:", zh2.ev(tab, r"""(()=>{const h=document.querySelector('.public-DraftEditor-content');
 const out=[]; const blocks=[...h.querySelectorAll('[data-block]')];
 blocks.forEach((b,i)=>{ if(b.querySelector('img')) out.push({i, txt:(b.innerText||'').replace(/\s+/g,' ').slice(0,50),
   prev: blocks[i-1]?(blocks[i-1].innerText||'').replace(/\s+/g,' ').slice(0,34):null});});
 return JSON.stringify(out,null,1);})()"""))
print("dialog open:", zh2.ev(tab, r"""(()=>{const d=[...document.querySelectorAll('div')].find(e=>{const r=e.getBoundingClientRect();
 return r.width>250&&r.height>120&&(e.innerText||'').includes('添加图片注释')});
 return d?JSON.stringify((d.innerText||'').replace(/\s+/g,' ').slice(0,150)):'none';})()"""))
print("shot:", zh2.shot(tab, "_zh_now.png"))
