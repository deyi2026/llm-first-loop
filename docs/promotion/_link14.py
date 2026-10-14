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
        print("URL:", await ev("location.href"))
        print("LINKS:", await ev("""JSON.stringify([...document.querySelectorAll('a[href*="toutiao.com/article"],a[href*="/article/"]')].map(a=>a.href+' :: '+(a.innerText||'').replace(/\\s+/g,' ').slice(0,40)).slice(0,8))"""))
        print("ALLHREF:", await ev("""JSON.stringify([...new Set([...document.querySelectorAll('a[href]')].map(a=>a.href).filter(h=>/article|detail|preview/.test(h)))].slice(0,10))"""))
        print("ROW0:", await ev("""(()=>{const rows=[...document.querySelectorAll('tbody tr, [class*=table] [class*=row]')];
          if(!rows.length) return 'NO_ROWS:'+document.querySelectorAll('table').length;
          return JSON.stringify(rows.slice(0,2).map(r=>{const a=r.querySelector('a'); return (r.innerText||'').replace(/\\s+/g,' ').slice(0,80)+' || '+(a?a.href:'NO_A');}));})()"""))
asyncio.run(main())
