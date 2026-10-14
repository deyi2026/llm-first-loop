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
        print("TOOLBAR:", await ev("""JSON.stringify([...document.querySelectorAll('.syl-toolbar-tool')].map((x,k)=>({k,
          title:(x.getAttribute('data-title')||x.getAttribute('title')||'').slice(0,14),
          cls:(x.className||'').slice(0,44), txt:(x.innerText||'').trim().slice(0,10)})))"""))
        print("DECL:", await ev("""(()=>{const t=document.body.innerText; const i=t.indexOf('声明');
          const els=[...document.querySelectorAll('label,span,div')].filter(e=>(e.innerText||'').trim()==='声明').slice(0,3);
          return JSON.stringify({ctx:t.slice(Math.max(0,i-60),i+120).replace(/\\s+/g,' '), els:els.map(e=>({tag:e.tagName,cls:(e.className||'').slice(0,40)}))});})()"""))
        print("TOPIC_BTN:", await ev("""JSON.stringify([...document.querySelectorAll('[class*=topic],[class*=tag],[class*=Topic]')].map(x=>({cls:(x.className||'').slice(0,50), txt:(x.innerText||'').replace(/\\s+/g,' ').slice(0,16), vis:!!(x.offsetParent||x.getClientRects().length)})).filter(o=>o.vis).slice(0,12))"""))
asyncio.run(main())
