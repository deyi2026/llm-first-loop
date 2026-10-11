import zh, json
tid = json.load(open("_zh_tid.json"))
zh.activate(tid)
print("pages now:", [p.get("url","")[:60] for p in zh._pages() if "zhihu" in p.get("url","")])
# A) title textarea
ta = "document.querySelector('textarea')"
print("textarea cls:", zh.ev(tid, ta + ".className"))
print("title before:", zh.ev(tid, ta + ".value"))
print("click title:", zh.click(tid, ta))
print("insertText title:", zh.typ(tid, "TEST", wait=0.8))
print("title after:", zh.ev(tid, ta + ".value"))
# B) wheel event sanity
zh.call(tid, lambda s,a: s("Input.dispatchMouseEvent", {"type":"mouseWheel","x":500,"y":500,"deltaX":0,"deltaY":200}), wait=0.5)
print("scrollY:", zh.ev(tid, "window.scrollY"))
