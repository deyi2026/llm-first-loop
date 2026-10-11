import zh, json
tid = json.load(open("_zh_tid.json"))
print("SHOT:", zh.shot(tid, "_zh_modal.png"))
print("BODY:", zh.ev(tid, "document.body.innerText.replace(/\\s+/g,' ').slice(0,300)"))
print("DIALOGS:", zh.ev(tid, r"""(()=>{const out=[];
  document.querySelectorAll('[role=dialog],[class*=Modal],[class*=modal],[class*=Dialog],[class*=dialog]').forEach(e=>{
    const r=e.getBoundingClientRect();
    out.push({cls:String(e.className).slice(0,50), w:Math.round(r.width), h:Math.round(r.height),
              vis:r.width>0&&r.height>0, txt:(e.innerText||'').replace(/\s+/g,' ').slice(0,140)});});
  return JSON.stringify(out.filter(o=>o.vis),null,1);})()"""))
