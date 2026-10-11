import _cdp, json, urllib.request, asyncio, websockets, time

async def open_and_read(url, js):
    async with websockets.connect(_cdp.browser_ws(), max_size=200*1024*1024) as ws:
        n = [0]
        async def send(method, params, sid=None):
            n[0] += 1
            msg = {"id": n[0], "method": method, "params": params}
            if sid: msg["sessionId"] = sid
            await ws.send(json.dumps(msg))
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 30))
                if m.get("id") == n[0]: return m
        r = await send("Target.createTarget", {"url": url})
        tid = r["result"]["targetId"]
        a = await send("Target.attachToTarget", {"targetId": tid, "flatten": True})
        sid = a["result"]["sessionId"]
        await asyncio.sleep(3)
        out = await send("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True}, sid)
        await send("Target.closeTarget", {"targetId": tid})
        return out

JS = r"""
(()=>{
  const art = document.querySelector('article') || document.querySelector('.Post-RichText') || document.body;
  const txt = art.innerText || '';
  return JSON.stringify({
    url: location.href,
    title: (document.querySelector('h1')||{}).innerText || document.title,
    len: txt.replace(/\s/g,'').length,
    p: art.querySelectorAll('p').length,
    h1: art.querySelectorAll('h1').length,
    h2: art.querySelectorAll('h2').length,
    h3: art.querySelectorAll('h3').length,
    li: art.querySelectorAll('li').length,
    pre: art.querySelectorAll('pre').length,
    img: art.querySelectorAll('img').length,
    literalMd: {'hashHead':(txt.match(/^#{1,3} /gm)||[]).length,
                'boldAst':(txt.match(/\*\*/g)||[]).length,
                'gt':(txt.match(/^> /gm)||[]).length,
                'pipe':(txt.match(/\|---/g)||[]).length},
    head: txt.replace(/\s+/g,' ').slice(0,200),
    tail: txt.replace(/\s+/g,' ').slice(-160)
  });
})()
"""
r = asyncio.run(open_and_read("https://zhuanlan.zhihu.com/p/2092334918437230422", JS))
res = r.get("result", {})
print(json.dumps(res.get("result", {}).get("value"), ensure_ascii=False, indent=1))
if "exceptionDetails" in res: print("EXC", json.dumps(res["exceptionDetails"], ensure_ascii=False)[:600])
