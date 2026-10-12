import zh, json
tid = json.load(open("_zh_tid.json"))
print("IMPORT:", zh.click(tid, "[...document.querySelectorAll('button')].find(b=>b.innerText.includes('导入'))"))
print("MODAL:", zh.ev(tid, r"""(()=>{
  const m=[...document.querySelectorAll('div')].filter(e=>{const r=e.getBoundingClientRect();
     const cs=getComputedStyle(e); return cs.position==='fixed'&&r.width>250&&r.height>100;});
  const d=m[m.length-1];
  if(!d) return JSON.stringify({err:'no modal'});
  return JSON.stringify({text:d.innerText.replace(/\s+/g,' ').slice(0,240),
   btns:[...d.querySelectorAll('button')].map(b=>({t:(b.innerText||'').replace(/[\s]/g,''),d:b.disabled})),
   tas:[...d.querySelectorAll('textarea,input')].map(i=>({tag:i.tagName,type:i.type,ph:i.placeholder||'',cls:String(i.className).slice(0,45)})),
   fileAccept:[...d.querySelectorAll('input[type=file]')].map(i=>i.accept)});})()"""))
