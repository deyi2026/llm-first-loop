import zh2, json, time
tab = zh2.pick("/edit"); zh2.activate(tab)
print("click 导入文档:", zh2.click(tab, "[...document.querySelectorAll('button')].find(b=>b.innerText.includes('导入文档'))"))
time.sleep(2)
print("shot:", zh2.shot(tab, "_zh_import2.png"))
print("dialogs:", zh2.ev(tab, r"""(()=>{const out=[];
 document.querySelectorAll('div').forEach(e=>{const cs=getComputedStyle(e); const r=e.getBoundingClientRect();
  if((cs.position==='fixed'||cs.position==='absolute')&&r.width>220&&r.height>80)
   out.push({cls:String(e.className).slice(0,40),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),
             txt:(e.innerText||'').replace(/\s+/g,' ').slice(0,150)});});
 return JSON.stringify(out.slice(0,8),null,1);})()"""))
print("textareas:", zh2.ev(tab, "JSON.stringify([...document.querySelectorAll('textarea')].map(t=>({ph:t.placeholder,cls:String(t.className).slice(0,40),vis:t.getBoundingClientRect().height>0})))"))
