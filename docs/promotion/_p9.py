import zh, json
tid = json.load(open("_zh_tid.json"))
zh.activate(tid)
print("click:", zh.click(tid, "document.querySelector('.public-DraftEditor-content')"))
print("activeElement:", zh.ev(tid, "document.activeElement.className"))
print("sel:", zh.ev(tid, r"""(()=>{const s=window.getSelection();
 return JSON.stringify({anchor:s.anchorNode?(s.anchorNode.nodeName||'text'):null, off:s.anchorOffset,
 collapsed:s.isCollapsed, inEd:!!(s.anchorNode&&s.anchorNode.closest&&s.anchorNode.closest('.public-DraftEditor-content'))});})()"""))
print("typ 'ZZ':", zh.typ(tid, "ZZ", wait=1.2))
print("counter:", zh.counter(tid))
