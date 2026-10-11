import zh, json
tid = json.load(open("_zh_tid.json"))
print("focus:", zh.click(tid, "document.querySelector('.public-DraftEditor-content')"))
print("activeElement:", zh.ev(tid, r"""(()=>{const a=document.activeElement;return JSON.stringify({tag:a.tagName,cls:String(a.className).slice(0,60),editable:a.isContentEditable});})()"""))
print("-- insertText probe --")
print("typ:", zh.typ(tid, "X"))
print("counter:", zh.counter(tid))
print("-- selection-based clear --")
print("selectAllChildren:", zh.ev(tid, r"""(()=>{const ed=document.querySelector('.public-DraftEditor-content');
  const s=window.getSelection(); const r=document.createRange(); r.selectNodeContents(ed);
  s.removeAllRanges(); s.addRange(r); return JSON.stringify({selLen:s.toString().length});})()"""))
print("Backspace:", zh.key(tid, "Backspace"))
print("counter:", zh.counter(tid))
