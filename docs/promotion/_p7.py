import zh, json
tid = json.load(open("_zh_tid.json"))
zh.activate(tid)
zh.click(tid, "document.querySelector('.public-DraftEditor-content')")
print("sel:", zh.ev(tid, r"""(()=>{const s=window.getSelection();
 return JSON.stringify({anchor:s.anchorNode?s.anchorNode.name:null, off:s.anchorOffset, collapsed:s.isCollapsed,
   inEd: !!s.anchorNode && !!s.anchorNode.closest && !!s.anchorNode.closest('.public-DraftEditor-content')});})()"""))
print("html len:", zh.ev(tid, "document.querySelector('.public-DraftEditor-content').textContent.length"))
print("typ 'ZZ':", zh.typ(tid, "ZZ", wait=1.2))
print("html len after:", zh.ev(tid, "document.querySelector('.public-DraftEditor-content').textContent.length"))
print("counter:", zh.counter(tid))
print("-- try keyDown char event --")
print(zh.key(tid, "a"))
print("html len after key:", zh.ev(tid, "document.querySelector('.public-DraftEditor-content').textContent.length"))
