import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def tg():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "mp.toutiao.com/profile_v4/graphic" in t.get("url","")]
async def main():
    t=tg()[0]
    async with websockets.connect(t["webSocketDebuggerUrl"],max_size=200*1024*1024) as ws:
        i=[0]
        async def ev(e):
            i[0]+=1
            await ws.send(json.dumps({"id":i[0],"method":"Runtime.evaluate","params":{"expression":e,"returnByValue":True,"awaitPromise":True}}))
            while True:
                m=json.loads(await ws.recv())
                if m.get("id")==i[0]:
                    if "exceptionDetails" in m.get("result",{}): return "ERR:"+str(m["result"]["exceptionDetails"].get("text"))
                    return m.get("result",{}).get("result",{}).get("value")
        print("LIST:", await ev("""(()=>{const rows=[...document.querySelectorAll('tr,[class*=table-row],[class*=content-row]')];
          const out=rows.map(r=>{const a=r.querySelector('a[href]'); const t=(r.innerText||'').replace(/\\s+/g,' ').slice(0,70);
            return (t)+' || '+(a?a.href.slice(0,80):'');}).filter(x=>x.length>20);
          return JSON.stringify(out.slice(0,6));})()"""))
asyncio.run(main())
