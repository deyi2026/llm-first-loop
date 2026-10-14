# -*- coding: utf-8 -*-
import asyncio, json, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
arr = json.load(urllib.request.urlopen(CDP + "/json", timeout=8))
t = [x for x in arr if x.get("type") == "page" and "juejin.cn" in x.get("url", "") and "editor" not in x.get("url","")][-1]
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
        print(await ev("""fetch('https://api.juejin.cn/content_api/v1/article/query_list',{
          method:'POST',credentials:'include',
          headers:{'content-type':'application/json'},
          body:JSON.stringify({cursor:'0',limit:3,sort_type:2})})
          .then(r=>r.json()).then(j=>JSON.stringify(j).slice(0,1200))"""))
asyncio.run(main())
