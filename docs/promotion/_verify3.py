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
        print(await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const imgs=[...pm.querySelectorAll('img')].map(x=>({w:x.naturalWidth,h:x.naturalHeight,
            inPM: pm.contains(x), src:(x.src||'').slice(0,60)}));
          const kids=[...pm.children].map(c=>c.tagName+'.'+((c.className||'').split(' ')[0]||''));
          return JSON.stringify({imgCount:imgs.length, imgs:imgs.slice(0,6),
            topLevel:kids.slice(0,24), childCount:pm.children.length},null,0);})()"""))
asyncio.run(main())
