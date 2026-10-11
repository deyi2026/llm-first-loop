import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def tt():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "toutiao" in t.get("url","")]
async def main():
    ts=tt()
    if not ts: raise SystemExit("no toutiao tab")
    t=ts[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def ev(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    rr=m.get("result",{}).get("result",{})
                    return rr.get("value", rr.get("description"))
        print("URL:", await ev("location.href"))
        print("ROWS:", await ev("""(()=>{const rows=[...document.querySelectorAll('tr,[class*=table-row],[class*=article-item]')]
          .map(r=>r.innerText.replace(/\\n+/g,' | ').slice(0,180)).filter(s=>s.length>10);
          return JSON.stringify(rows.slice(0,6),null,1);})()"""))
asyncio.run(main())
