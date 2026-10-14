import asyncio, json, urllib.request, websockets
CDP="http://127.0.0.1:9229"
def tg():
    d=json.load(urllib.request.urlopen(CDP+"/json"))
    return [t for t in d if t.get("type")=="page" and "profile_v4/graphic/publish" in t.get("url","")]
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
        print("INPUTS:", await ev("""JSON.stringify([...document.querySelectorAll('input,textarea')].map((x,k)=>({k,tag:x.tagName,
          ph:(x.placeholder||'').slice(0,18), val:(x.value||'').slice(0,30), cls:(x.className||'').slice(0,30),
          vis:!!(x.offsetParent||x.getClientRects().length)})).filter(o=>o.vis))"""))
        print("BUTTONS:", await ev("""JSON.stringify([...document.querySelectorAll('button,a[class*=btn],div[class*=cover],div[class*=topic],div[class*=declar]')].map(x=>({t:x.tagName,
          txt:(x.innerText||'').replace(/\\s+/g,' ').slice(0,18), cls:(x.className||'').slice(0,40),
          vis:!!(x.offsetParent||x.getClientRects().length)})).filter(o=>o.vis&&o.txt).slice(0,40))"""))
        print("TEXT_HITS:", await ev("""(()=>{const t=document.body.innerText; const out=[];
          for(const k of ['封面','话题','标签','声明','原创','互动']) if(t.includes(k)) out.push(k);
          return JSON.stringify(out);})()"""))
asyncio.run(main())
