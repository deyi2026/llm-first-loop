import zh, json
tid = json.load(open("_zh_tid.json"))
zh.activate(tid)
ed = "document.querySelector('.public-DraftEditor-content')"
print("rect:", zh.ev(tid, "(()=>{const r=%s.getBoundingClientRect();return JSON.stringify({t:r.top,l:r.left,w:r.width,h:r.height});})()" % ed))
print("elementFromPoint:", zh.ev(tid, r"""(()=>{const r=document.querySelector('.public-DraftEditor-content').getBoundingClientRect();
 const x=r.left+r.width/2, y=r.top+r.height/2;
 const el=document.elementFromPoint(x,y);
 return JSON.stringify({x:Math.round(x),y:Math.round(y),tag:el&&el.tagName,cls:String(el&&el.className).slice(0,60),editable:!!(el&&el.closest('[contenteditable]'))});})()"""))
print("-- 导入 caret --")
print("import btn html:", zh.ev(tid, r"""(()=>{const b=[...document.querySelectorAll('button')].find(b=>b.innerText.includes('导入'));return b?b.outerHTML.slice(0,600):'none';})()"""))
print("click import caret:", zh.click(tid, "[...document.querySelectorAll('button')].find(b=>b.innerText.includes('导入')).querySelector('svg')||[...document.querySelectorAll('button')].find(b=>b.innerText.includes('导入'))"))
print("menus:", zh.ev(tid, r"""(()=>{const out=[];
 document.querySelectorAll('[class*=Menu],[class*=menu],[class*=Dropdown],[class*=dropdown],[role=menu]').forEach(e=>{const r=e.getBoundingClientRect();
  if(r.width>0&&r.height>0) out.push({cls:String(e.className).slice(0,45),txt:(e.innerText||'').replace(/\s+/g,' ').slice(0,90)});});
 return JSON.stringify(out.slice(0,8),null,1);})()"""))
