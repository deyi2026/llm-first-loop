import zh2, json, os, time
tab = zh2.pick("/edit"); zh2.activate(tab)
NEXT_JS = r"""(()=>{const h=[...document.querySelectorAll('.public-DraftEditor-content h2')]
  .find(e=>(e.innerText||'').trim().startsWith('哲学一：事实是一种有结构的'));
 if(!h) return null;
 const blk=h.closest('[data-block]')||h;
 let n=blk.nextElementSibling; while(n && !(n.hasAttribute&&n.hasAttribute('data-block'))) n=n.nextElementSibling;
 const t=n||blk; t.scrollIntoView({block:'center'});
 return JSON.stringify({txt:(t.innerText||'').slice(0,40)});})()"""
print("next block:", zh2.ev(tab, NEXT_JS))
print("click next:", zh2.click(tab, r"""(()=>{const h=[...document.querySelectorAll('.public-DraftEditor-content h2')]
  .find(e=>(e.innerText||'').trim().startsWith('哲学一：事实是一种有结构的'));
 const blk=h.closest('[data-block]')||h; let n=blk.nextElementSibling;
 while(n && !(n.hasAttribute&&n.hasAttribute('data-block'))) n=n.nextElementSibling;
 return n||blk;})()"""))
print("activeElement:", zh2.ev(tab, "document.activeElement.tagName+'.'+String(document.activeElement.className).slice(0,40)"))
print("selection in editor:", zh2.ev(tab, r"""(()=>{const s=window.getSelection();let n=s.anchorNode,inEd=false;
 while(n){if(n.classList&&n.classList.contains('public-DraftEditor-content')){inEd=true;break;}n=n.parentElement||n.parentNode;}
 let blk=null,p=s.anchorNode; while(p){if(p.getAttribute&&p.getAttribute('data-block')!==null){blk=p;break;}p=p.parentElement;}
 return JSON.stringify({inEd,block:blk?(blk.innerText||'').replace(/\s+/g,' ').slice(0,50):null,off:s.anchorOffset});})()"""))
