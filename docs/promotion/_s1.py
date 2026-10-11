import _cdp2, json
t = _cdp2.Tab("https://zhuanlan.zhihu.com/p/2092334918437230422/edit", wait=7)
print("COUNTER_BEFORE:", t.counter())
print("CLICK_IMPORT:", t.click("[...document.querySelectorAll('button')].find(b=>b.innerText.trim()==='导入')"))
print("AFTER_MODAL:", t.ev(r"""(()=>{
  const m=[...document.querySelectorAll('div')].filter(e=>{const r=e.getBoundingClientRect();
     const cs=getComputedStyle(e); return cs.position==='fixed'&&r.width>250&&r.height>120;});
  const d=m[m.length-1];
  if(!d) return JSON.stringify({err:'no modal'});
  return JSON.stringify({
    text:d.innerText.replace(/\s+/g,' ').slice(0,260),
    btns:[...d.querySelectorAll('button')].map(b=>(b.innerText||'').trim()).filter(Boolean),
    inputs:[...d.querySelectorAll('input,textarea')].map(i=>({tag:i.tagName,type:i.type,ph:i.placeholder||''})),
    fileInputs:[...d.querySelectorAll('input[type=file]')].map(i=>i.accept)
  });
})()"""))
import pickle; pickle.dump(t.tid, open('_tab.pkl','wb'))
print("TID:", t.tid)
