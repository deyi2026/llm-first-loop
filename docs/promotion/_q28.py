import zh2, json, os, time
tab = zh2.pick("/edit"); zh2.activate(tab)
ANCHOR = "哲学一：事实是一种有结构的"
# scroll the anchor into view and click it
print("locate:", zh2.ev(tab, """(()=>{const b=[...document.querySelectorAll('.public-DraftEditor-content h2,.public-DraftEditor-content div')]
  .find(e=>(e.innerText||'').trim().startsWith(%s));
 if(!b) return 'not found';
 b.scrollIntoView({block:'center'}); const r=b.getBoundingClientRect();
 window.__r=JSON.stringify({x:r.left+r.width/2,y:r.top+r.height/2,w:r.width,h:r.height});
 return window.__r;})()""" % json.dumps(ANCHOR)))
time.sleep(1)
pos = zh2.ev(tab, "(()=>{const b=[...document.querySelectorAll('.public-DraftEditor-content h2,.public-DraftEditor-content div')].find(e=>(e.innerText||'').trim().startsWith('哲学一：事实是一种有结构的')); if(!b) return null; const r=b.getBoundingClientRect(); return JSON.stringify({x:r.left+r.width/2,y:r.top+r.height/2,w:r.width,h:r.height});})()")
p = json.loads(pos)
print("click heading:", zh2.click(tab, "(()=>{const b=[...document.querySelectorAll('.public-DraftEditor-content h2,.public-DraftEditor-content div')].find(e=>(e.innerText||'').trim().startsWith('哲学一：事实是一种有结构的')); return b;})()"))
print("caret block:", zh2.ev(tab, "(()=>{const s=window.getSelection(); let n=s.anchorNode; while(n&&!(n.classList&&n.classList.contains('public-DraftEditor-content')))n=n.parentElement; const bl=s.anchorNode&&s.anchorNode.closest?n.closest('[data-block]'):null; return bl?(bl.innerText||'').slice(0,40):'none';})()"))
zh2.vk(tab, "ArrowDown", "ArrowDown", 40); zh2.vk(tab, "Home", "Home", 36)
zh2.vk(tab, "Enter", "Enter", 13)
print("after enter:", zh2.counter(tab))
