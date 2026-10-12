import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def tg():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "toutiao" in t.get("url","")]
async def main():
    t=tg()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def ev(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True,"awaitPromise":True}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]: return m.get("result",{}).get("result",{}).get("value")
        print(await ev("""(()=>{const rows=[...document.querySelectorAll('tr,[class*=table-row],[class*=article-item],[class*=list-item]')]
          .map(r=>r.innerText.replace(/\\n+/g,' | ').slice(0,220)).filter(s=>s.length>10);
          return JSON.stringify({url:location.href.slice(0,90), rows:rows.slice(0,8)},null,1);})()"""))
asyncio.run(main())
