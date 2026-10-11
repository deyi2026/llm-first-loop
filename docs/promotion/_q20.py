import zh2, json, time
tab = zh2.pick("/edit"); zh2.activate(tab)
print("click 图片:", zh2.click(tab, "[...document.querySelectorAll('button')].find(b=>b.innerText.includes('图片'))"))
time.sleep(1.5)
print("popover:", zh2.ev(tab, r"""(()=>{const out=[];
 document.querySelectorAll('div,li,button').forEach(e=>{const r=e.getBoundingClientRect(); const cs=getComputedStyle(e);
  const txt=(e.innerText||'').replace(/\s+/g,' ').trim();
  if(r.width>0&&r.height>0&&txt&&txt.length<14&&e.children.length===0&&(cs.position==='absolute'||cs.position==='fixed'||cs.position==='relative'))
   out.push({tag:e.tagName,txt,y:Math.round(r.top),cls:String(e.className).slice(0,35)});});
 return JSON.stringify(out.slice(0,14),null,1);})()"""))
print("shot:", zh2.shot(tab, "_zh_img.png"))
