import zh, json
tid = json.load(open("_zh_tid.json"))
zh.activate(tid)
zh.click(tid, "document.querySelector('.public-DraftEditor-content')")
print("sel:", zh.ev(tid, r"""(()=>{const s=window.getSelection(); let n=s.anchorNode;
  let inEd=false; while(n){ if(n.classList && n.classList.contains('public-DraftEditor-content')){inEd=true;break;} n=n.parentElement||n.parentNode; }
  return JSON.stringify({inEd, selText:s.toString().slice(0,40), rangeCount:s.rangeCount});})()"""))
L = "document.querySelector('.public-DraftEditor-content').textContent.length"
print("len before:", zh.ev(tid, L))
print("insertText:", zh.typ(tid, "ZZ", wait=1.0))
print("len after insertText:", zh.ev(tid, L))
print("-- char event --")
print(zh.ev(tid, "void 0"))
import asyncio
async def ch(tid, text):
    return zh.call(tid, lambda s,a: s("Input.dispatchKeyEvent", {"type":"char","text":text,"key":text,"modifiers":0}), wait=1.0)
print("char event:", ch(tid, "啊"))
print("len after char:", zh.ev(tid, L))
print("counter:", zh.counter(tid))
