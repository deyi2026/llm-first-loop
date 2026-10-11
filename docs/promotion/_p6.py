import zh, json
tid = json.load(open("_zh_tid.json"))
print("hidden?", zh.ev(tid, "JSON.stringify({hidden:document.hidden, vis:document.visibilityState, focus:document.hasFocus()})"))
print(zh.activate(tid))
print("after activate:", zh.ev(tid, "JSON.stringify({hidden:document.hidden, vis:document.visibilityState, focus:document.hasFocus()})"))
print("focus editor:", zh.click(tid, "document.querySelector('.public-DraftEditor-content')"))
print("activeElement:", zh.ev(tid, r"""(()=>{const a=document.activeElement;return JSON.stringify({tag:a.tagName,cls:String(a.className).slice(0,60),editable:a.isContentEditable});})()"""))
print("typ X:", zh.typ(tid, "X"))
print("counter:", zh.counter(tid))
