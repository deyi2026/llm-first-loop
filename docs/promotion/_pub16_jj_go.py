# -*- coding: utf-8 -*-
"""Clear tag input, close dropdown, click 确定并发布, poll for /post/<id>."""
import asyncio, json, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
arr = json.load(urllib.request.urlopen(CDP + "/json", timeout=8))
t = [x for x in arr if x.get("type") == "page" and "juejin.cn/editor" in x.get("url", "")][-1]
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
        print("CLEAR", await ev("""(()=>{const s=[...document.querySelectorAll('.byte-select')]
          .find(x=>x.offsetParent&&x.querySelector('input,textarea')&&x.innerText.indexOf('请搜索添加')<0);
          if(!s)return 'NO_SEL';const i=s.querySelector('input,textarea');
          const proto=i.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
          Object.getOwnPropertyDescriptor(proto,'value').set.call(i,'');
          i.dispatchEvent(new Event('input',{bubbles:true}));
          i.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
          i.dispatchEvent(new KeyboardEvent('keyup',{key:'Escape',bubbles:true}));
          return 'CLEARED';})()"""))
        await asyncio.sleep(1.0)
        print("CHIPS_FINAL", await ev("""(()=>{const s=[...document.querySelectorAll('.byte-select')]
          .find(x=>x.offsetParent&&x.querySelector('input,textarea')&&x.innerText.indexOf('请搜索添加')<0);
          if(!s)return 'NO_SEL';
          return JSON.stringify([...s.querySelectorAll('.byte-tag')].map(c=>(c.innerText||'').trim()));})()"""))
        print("PANEL_OPEN", await ev("(()=>{return !![...document.querySelectorAll('button')].find(x=>x.offsetParent&&x.textContent.trim()==='确定并发布');})()"))
        print("FINAL", await ev("""(()=>{const b=[...document.querySelectorAll('button')]
          .find(x=>x.offsetParent&&x.textContent.trim()==='确定并发布'&&!x.disabled);
          if(!b)return 'NO_FINAL';b.click();return 'CLICKED';})()"""))
        for _ in range(12):
            await asyncio.sleep(3)
            u = await ev("location.href")
            print("URL", u, flush=True)
            if "/post/" in u or "/editor/drafts" not in u: break
        print("BODY_HEAD", str(await ev("document.body.innerText"))[:300])
asyncio.run(main())
