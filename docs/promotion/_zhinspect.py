import _cdp, json, asyncio, websockets, time, sys

async def open_and_read(url, js, wait=6):
    async with websockets.connect(_cdp.browser_ws(), max_size=200*1024*1024) as ws:
        n=[0]
        async def send(method, params, sid=None):
            n[0]+=1; msg={"id":n[0],"method":method,"params":params}
            if sid: msg["sessionId"]=sid
            await ws.send(json.dumps(msg))
            while True:
                m=json.loads(await asyncio.wait_for(ws.recv(),30))
                if m.get("id")==n[0]: return m
        r=await send("Target.createTarget",{"url":url}); tid=r["result"]["targetId"]
        a=await send("Target.attachToTarget",{"targetId":tid,"flatten":True}); sid=a["result"]["sessionId"]
        await asyncio.sleep(wait)
        out=await send("Runtime.evaluate",{"expression":js,"returnByValue":True,"awaitPromise":True},sid)
        await send("Target.closeTarget",{"targetId":tid})
        return out

JS = r"""
(()=>{
  const ed = document.querySelector('.public-DraftEditor-content') || document.querySelector('[contenteditable]') || document.body;
  const t = ed.innerText || '';
  const counters = (document.body.innerText.match(/字数[：: ]*\d+/g)||[]);
  return JSON.stringify({
    url: location.href,
    titleVal: (document.querySelector('textarea[placeholder*="标题"]')||{}).value || '',
    editorLen: t.replace(/\s/g,'').length,
    editorLines: t.split('\n').filter(x=>x.trim()).length,
    counters,
    buttons: [...document.querySelectorAll('button')].map(b=>(b.innerText||'').trim()).filter(Boolean).slice(0,20),
    head: t.replace(/\s+/g,' ').slice(0,220),
    tail: t.replace(/\s+/g,' ').slice(-160)
  });
})()
"""
r = asyncio.run(open_and_read(sys.argv[1], JS))
res = r.get("result", {})
print(res.get("result", {}).get("value"))
