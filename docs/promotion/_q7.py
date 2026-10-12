import zh2, json
tab = zh2.pick("/edit"); zh2.activate(tab)
print("click 导入文档:", zh2.click(tab, "[...document.querySelectorAll('*')].find(e=>e.children.length===0 && e.innerText && e.innerText.trim().startsWith('导入文档'))"))
print("file inputs:", zh2.ev(tab, "JSON.stringify([...document.querySelectorAll('input[type=file]')].map(i=>({accept:i.accept, name:i.name||'', id:i.id||'', cls:String(i.className).slice(0,40)})))"))
print("modals:", zh2.ev(tab, r"""(()=>{const out=[];
 document.querySelectorAll('div').forEach(e=>{const r=e.getBoundingClientRect(); const cs=getComputedStyle(e);
  if(r.width>250&&r.height>100&&r.y<600&&(cs.position==='fixed'||cs.position==='absolute'))
   out.push({cls:String(e.className).slice(0,45),y:Math.round(r.y),txt:(e.innerText||'').replace(/\s+/g,' ').slice(0,120)});});
 return JSON.stringify(out.slice(0,6),null,1);})()"""))
