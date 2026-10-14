# -*- coding: utf-8 -*-
"""Probe juejin publish panel: real selected tags via byte-select DOM."""
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
        print("SEL_HTML", await ev("""(()=>{const sels=[...document.querySelectorAll('.byte-select')];
          const out=[];
          for(const s of sels){if(!s.offsetParent)continue;
            out.push({html:s.innerHTML.replace(/\\s+/g,' ').slice(0,400)});}
          return JSON.stringify(out);})()"""))
asyncio.run(main())
