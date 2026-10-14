# -*- coding: utf-8 -*-
"""Dump open portal dropdown options with full classes + disabled state."""
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
        print("DROPDOWN", await ev("""(()=>{const dd=[...document.querySelectorAll('[class*=byte-select-dropdown],[class*=byte-select__dropdown],.byte-select-popup')]
          .filter(x=>x.offsetParent);
          if(!dd.length)return 'NO_DD';
          return JSON.stringify(dd.map(d=>({cls:d.className.toString().slice(0,80),
            opts:[...d.querySelectorAll('[class*=byte-select-option]')].slice(0,8).map(o=>({
              txt:(o.innerText||'').trim().slice(0,20),
              cls:o.className.toString().replace(/byte-select-option/g,'').slice(0,50),
              dis:!!o.closest('[class*=disabled]')||o.className.includes('disabled')}))})));})()"""))
        print("CHIPS", await ev("""(()=>{const s=[...document.querySelectorAll('.byte-select')]
          .find(x=>x.offsetParent&&x.querySelector('input,textarea')&&x.innerText.indexOf('请搜索添加')<0);
          if(!s)return 'NO_SEL';
          return JSON.stringify([...s.querySelectorAll('.byte-tag')].map(c=>(c.innerText||'').trim()));})()"""))
asyncio.run(main())
