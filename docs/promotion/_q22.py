import zh2, json, os, time
tab = zh2.pick("/edit"); zh2.activate(tab)
print("click 本地上传:", zh2.click(tab, "[...document.querySelectorAll('*')].find(e=>e.children.length===0 && (e.innerText||'').trim()==='本地上传')"))
time.sleep(1.5)
print("file inputs now:", zh2.ev(tab, r"""(()=>{const out=[];
 document.querySelectorAll('input[type=file]').forEach((i,k)=>{const r=i.getBoundingClientRect();
  out.push({k,accept:i.accept.slice(0,50),vis:r.width>0&&r.height>0,cls:String(i.className).slice(0,30)});});
 return JSON.stringify(out);})()"""))
p = os.path.abspath("img/fig11-three-state-layers.png")
print("set file:", zh2.set_file2(tab, "[...document.querySelectorAll('input[type=file]')].filter(x=>x.accept.includes('image')).pop()", [p]))
time.sleep(5)
print("counter:", zh2.counter(tab))
print("imgs in editor:", zh2.ev(tab, "document.querySelectorAll('.public-DraftEditor-content img').length"))
