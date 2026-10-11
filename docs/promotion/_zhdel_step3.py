import _cdp
t = _cdp.pick("zhihu.com/creator")
print("delete-click:", _cdp.click_expr(t, "[...document.querySelectorAll('button')].find(b=>b.innerText.trim()==='删除' && b.getBoundingClientRect().height>0)"))
import time; time.sleep(1.5)
JS = r"""
(()=>{
  const dlgs=[...document.querySelectorAll('div')].filter(e=>{
     const cs=getComputedStyle(e); const r=e.getBoundingClientRect();
     return r.width>200&&r.height>80&&cs.position==='fixed';});
  const d=dlgs[dlgs.length-1];
  if(!d) return JSON.stringify({err:'no dialog'});
  return JSON.stringify({
    dialogText:d.innerText.replace(/\s+/g,' ').slice(0,300),
    btns:[...d.querySelectorAll('button')].map(b=>({txt:b.innerText.trim().slice(0,12),
      x:Math.round(b.getBoundingClientRect().left+b.getBoundingClientRect().width/2),
      y:Math.round(b.getBoundingClientRect().top+b.getBoundingClientRect().height/2)}))
  },null,1);
})()
"""
print(_cdp.ev(t, JS))
