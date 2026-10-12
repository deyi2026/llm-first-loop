import zh, json
tid = zh.open_tab("https://zhuanlan.zhihu.com/p/2092334918437230422/edit", wait=9)
json.dump(tid, open("_zh_tid.json", "w"))
print("TID:", tid)
print("URL:", zh.ev(tid, "location.href"))
print("COUNTER:", zh.counter(tid))
print("BTNS:", zh.ev(tid, "JSON.stringify([...document.querySelectorAll('button')].map(b=>(b.innerText||'').trim()).filter(Boolean).slice(0,25))"))
