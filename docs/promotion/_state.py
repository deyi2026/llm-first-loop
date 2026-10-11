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
          const ti=document.querySelector('textarea[placeholder*="标题"]');
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          const open=[...document.querySelectorAll('[class*=popover],[class*=popup],[class*=dialog],[class*=modal]')].filter(e=>e.offsetParent!==null).length;
          return JSON.stringify({title:ti?ti.value:null, words:wc?wc[1]:null,
            imgs:pm?pm.querySelectorAll('img').length:-1, links:pm?pm.querySelectorAll('a').length:-1,
            openPopups:open, files:document.querySelectorAll('input[type=file]').length,
            first80: pm?pm.innerText.slice(0,80).replace(/\\n/g,' / '):null});})()"""))
asyncio.run(main())
