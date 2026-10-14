# -*- coding: utf-8 -*-
"""Final verify (chips/category) then publish juejin draft."""
import asyncio, json, sys, urllib.request, websockets
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
        print("CHIPS2", await ev("""(()=>{const s=[...document.querySelectorAll('.byte-select')]
          .find(x=>x.offsetParent&&x.querySelector('input,textarea')&&x.innerText.indexOf('请搜索添加')<0);
          if(!s)return 'NO_SEL';
          return JSON.stringify([...s.querySelectorAll('.byte-tag')].map(c=>(c.innerText||'').trim()));})()"""))
        print("CATEGORY", await ev("""(()=>{const items=[...document.querySelectorAll('[class*=category] *,[class*=radio] *,label,span,div')]
          .filter(x=>x.offsetParent&&x.children.length===0&&['后端','前端','Android','iOS','人工智能','开发工具','代码人生','阅读'].includes(x.textContent.trim())
            &&(x.className&&typeof x.className==='string'&&(x.className.includes('active')||x.className.includes('checked')||x.className.includes('selected'))));
          return JSON.stringify(items.map(x=>x.textContent.trim()));})()"""))
        panel_open = await ev("(()=>{return !![...document.querySelectorAll('button')].find(x=>x.offsetParent&&x.textContent.trim()==='确定并发布');})()")
        print("PANEL_OPEN", panel_open)
        if not panel_open:
            print("REOPEN", await ev("""(()=>{const b=[...document.querySelectorAll('button')]
              .find(x=>x.offsetParent&&x.textContent.trim()==='发布');if(!b)return 'NO_PUB';b.click();return 'CLICKED';})()"""))
            await asyncio.sleep(3.5)
            print("CHIPS3", await ev("""(()=>{const s=[...document.querySelectorAll('.byte-select')]
              .find(x=>x.offsetParent&&x.querySelector('input,textarea')&&x.innerText.indexOf('请搜索添加')<0);
              if(!s)return 'NO_SEL';
              return JSON.stringify([...s.querySelectorAll('.byte-tag')].map(c=>(c.innerText||'').trim()));})()"""))
        if "--go" not in sys.argv:
            print("DRY_STOP"); return
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
