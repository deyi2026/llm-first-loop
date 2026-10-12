import zh2, json
tab = zh2.pick("/edit"); zh2.activate(tab)
print("shot:", zh2.shot(tab, "_zh_import.png"))
print("popovers:", zh2.ev(tab, r"""(()=>{const out=[];
 document.querySelectorAll('div,ul').forEach(e=>{const cs=getComputedStyle(e); const r=e.getBoundingClientRect();
  if((cs.position==='absolute'||cs.position==='fixed')&&r.width>80&&r.height>20&&r.height<400&&r.y<400)
   out.push({cls:String(e.className).slice(0,50),pos:cs.position,y:Math.round(r.y),txt:(e.innerText||'').replace(/\s+/g,' ').slice(0,80)});});
 return JSON.stringify(out.slice(0,10),null,1);})()"""))
