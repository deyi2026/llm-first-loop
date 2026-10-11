import zh2, json, os, time
tab = zh2.pick("/edit"); zh2.activate(tab)
print("click 上传图片:", zh2.click(tab, "[...document.querySelectorAll('button')].find(b=>b.innerText.trim()==='上传图片')"))
time.sleep(1.5)
print("shot:", zh2.shot(tab, "_zh_img2.png"))
print("file inputs:", zh2.ev(tab, r"""(()=>{const out=[];
 document.querySelectorAll('input[type=file]').forEach((i,k)=>{const r=i.getBoundingClientRect();
  out.push({k,accept:i.accept.slice(0,60),vis:r.width>0&&r.height>0,cls:String(i.className).slice(0,35)});});
 return JSON.stringify(out);})()"""))
