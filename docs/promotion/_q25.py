import zh2, json
tab = zh2.pick("/edit"); zh2.activate(tab)
print("modal imgs:", zh2.ev(tab, r"""(()=>{const out=[];
 document.querySelectorAll('img').forEach((i,k)=>{const r=i.getBoundingClientRect();
  if(r.width>20&&r.height>20&&r.top<800) out.push({k,src:(i.src||'').slice(-70),w:Math.round(r.width),h:Math.round(r.height),y:Math.round(r.top)});});
 return JSON.stringify(out,null,1);})()"""))
print("modal text:", zh2.ev(tab, r"""(()=>{const out=[];
 document.querySelectorAll('div').forEach(e=>{const r=e.getBoundingClientRect();
  const t=(e.innerText||'').replace(/\s+/g,' ').trim();
  if(r.width>250&&r.height>150&&r.top<700&&t&&t.length<120&&e.children.length<12) out.push(t);});
 return JSON.stringify(out.slice(0,6),null,1);})()"""))
