import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
d=json.load(urllib.request.urlopen(CDP+"/json"))
pg=[t for t in d if t.get("type")=="page"]
for t in pg: print("TAB:", t["url"][:90])
zt=[t for t in pg if "zhihu" in t.get("url","")]
if not zt: raise SystemExit("NO_ZHIHU_TAB")
async def main():
    t=zt[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def ev(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True,"awaitPromise":True}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]: return m.get("result",{}).get("result",{}).get("value")
        print("STATE:", await ev("""(()=>{const ta=[...document.querySelectorAll('textarea')];
          const inp=[...document.querySelectorAll('input')].map(x=>x.placeholder||x.type).filter(Boolean).slice(0,8);
          return JSON.stringify({url:location.href.slice(0,80), title:location.href.includes('/write'),
            textareas:ta.map(x=>x.placeholder||x.className.slice(0,30)), inputs:inp,
            bodyStart:document.body.innerText.slice(0,150).replace(/\\n+/g,' / ')});})()"""))
asyncio.run(main())
