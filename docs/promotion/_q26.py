import zh2, json, time
tab = zh2.pick("/edit"); zh2.activate(tab)
print("insert:", zh2.click(tab, "[...document.querySelectorAll('button')].find(b=>b.innerText.trim()==='插入图片')"))
time.sleep(4)
print("counter:", zh2.counter(tab))
print("editor imgs:", zh2.ev(tab, "document.querySelectorAll('.public-DraftEditor-content img').length"))
print("modal still open:", zh2.ev(tab, "!![...document.querySelectorAll('div')].find(e=>{const r=e.getBoundingClientRect();const t=(e.innerText||'');return r.width>250&&r.height>150&&t.includes('已上传')})"))
print("shot:", zh2.shot(tab, "_zh_ins.png"))
