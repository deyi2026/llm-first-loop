# -*- coding: utf-8 -*-
"""Pick tag option ONLY from body-level portal dropdown (exclude publish panel)."""
import asyncio, json, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
arr = json.load(urllib.request.urlopen(CDP + "/json", timeout=8))
t = [x for x in arr if x.get("type") == "page" and "juejin.cn/editor" in x.get("url", "")][-1]
PANEL_JS = """(()=>{const b=[...document.querySelectorAll('button')]
  .filter(x=>x.offsetParent&&x.textContent.trim()==='确定并发布');
  if(!b.length)return null;let p=b[0];
  for(let i=0;i<12&&p;i++){p=p.parentElement;
    if(p&&(p.innerText||'').includes('分类')&&(p.innerText||'').includes('标签'))return p;}
  return null;})()"""
async def main():
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=50*1024*1024) as ws:
        n = [0]
        async def ev(e):
            n[0] += 1
            await ws.send(json.dumps({"id": n[0], "method": "Runtime.evaluate",
                "params": {"expression": e, "returnByValue": True, "awaitPromise": True}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == n[0]:
                    r = m.get("result", {})
                    if "exceptionDetails" in r: raise RuntimeError(str(r["exceptionDetails"])[:250])
                    return r.get("result", {}).get("value")
        # 确保输入框有搜索词且下拉打开
        print("TYPE", await ev("""(()=>{const s=[...document.querySelectorAll('.byte-select')]
          .find(x=>x.offsetParent&&x.querySelector('input,textarea')&&x.innerText.indexOf('请搜索添加')<0);
          if(!s)return 'NO_SEL';s.click();const i=s.querySelector('input,textarea');if(!i)return 'NO_INPUT';
          const proto=i.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto,'value').set.call(i,'人工智能');
          i.dispatchEvent(new Event('input',{bubbles:true}));i.focus();return 'TYPED:'+i.value;})()"""))
        await asyncio.sleep(2.5)
        # 只点面板外的 portal 选项
        print("PICK_PORTAL", await ev("""(()=>{const panel=(%s);
          const cand=[...document.querySelectorAll('li,[class*=option],[class*=dropdown] *')]
          .filter(x=>x.offsetParent&&x.children.length===0&&x.tagName!=='INPUT'
            &&(x.innerText||'').trim()==='人工智能'
            &&!(panel&&panel.contains(x)));
          if(!cand.length)return 'NO_OPTION';
          cand[0].click();return 'PICKED:'+(cand[0].innerText||'').trim()
            +' cls='+(cand[0].className||'').toString().slice(0,40);})()""" % PANEL_JS))
        await asyncio.sleep(2.0)
        print("CHIPS", await ev("""(()=>{const s=[...document.querySelectorAll('.byte-select')]
          .find(x=>x.offsetParent&&x.querySelector('input,textarea')&&x.innerText.indexOf('请搜索添加')<0);
          if(!s)return 'NO_SEL';
          return JSON.stringify([...s.querySelectorAll('.byte-tag')].map(c=>(c.innerText||'').trim()));})()"""))
        print("INPUT_VAL", await ev("""(()=>{const s=[...document.querySelectorAll('.byte-select')]
          .find(x=>x.offsetParent&&x.querySelector('input,textarea')&&x.innerText.indexOf('请搜索添加')<0);
          const i=s&&s.querySelector('input,textarea');return i?('['+i.value+']'):'NO_INPUT';})()"""))
asyncio.run(main())
