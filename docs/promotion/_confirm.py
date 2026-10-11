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
        print("CONFIRM:", await ev("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='确认发布');
          if(!b) return 'NO_BTN'; b.click(); return 'CLICKED';})()"""))
        await asyncio.sleep(10)
        print("AFTER:", await ev("""(()=>{const vis=[...document.querySelectorAll('[class*=dialog],[class*=modal],[role=dialog]')].filter(e=>e.offsetParent!==null);
          return JSON.stringify({url:location.href.slice(0,110), dialogs:vis.length,
            dialogTxt:vis.map(e=>e.innerText.slice(0,220)).join(' || ').slice(0,300),
            toast:(()=>{const t=[...document.querySelectorAll('[class*=toast],[class*=message],[class*=notice]')].filter(e=>e.offsetParent!==null);
              return t.map(e=>e.innerText.slice(0,80)).join(' | ');})()});})()"""))
asyncio.run(main())
