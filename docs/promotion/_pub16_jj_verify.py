# -*- coding: utf-8 -*-
"""Public readback verify for juejin post."""
import asyncio, json, urllib.request, websockets
CDP = "http://127.0.0.1:9229"
URL = "https://juejin.cn/post/7696005650718998571"
KEYS = ["前缀缓存（prefix caching）", "缓存命中 0.006 美元", "5 分钟", "绝不跨组织", "核实日期 2026 年 10 月 13 日"]
arr = json.load(urllib.request.urlopen(CDP + "/json", timeout=8))
t = [x for x in arr if x.get("type") == "page" and "juejin.cn" in x.get("url", "")][-1]
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
        print(await ev("""fetch(%s,{credentials:'include'}).then(r=>r.text()).then(t=>{
          const d=new DOMParser().parseFromString(t,'text/html');
          const art=d.querySelector('article')||d.body;
          const ks=%s;
          return JSON.stringify({status_len:t.length,page_title:(d.querySelector('title')||{}).innerText||'',
            h1:(d.querySelector('article h1')||{}).innerText||'',
            keys:ks.map(k=>({k:k.slice(0,14),hit:art.innerText.replace(/\\s/g,'').includes(k.replace(/\\s/g,''))})),
            article_len:art.innerText.replace(/\\s/g,'').length,
            ai_note:art.innerText.includes('AI')});})""" % (json.dumps(URL), json.dumps(KEYS))))
asyncio.run(main())
