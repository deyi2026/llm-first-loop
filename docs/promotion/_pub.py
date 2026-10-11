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
                if m.get("id")==i[0]:
                    if "exceptionDetails" in m.get("result",{}): return "ERR:"+str(m["result"]["exceptionDetails"].get("text"))
                    return m.get("result",{}).get("result",{}).get("value")
        # 发布前最终守门
        print("PRE-GATE:", await ev("""(()=>{const pm=document.querySelector('.ProseMirror[contenteditable]');
          const ti=document.querySelector('textarea[placeholder*="标题"]');
          const wc=document.body.innerText.match(/共\\s*(\\d+)\\s*字/);
          const imgs=[...pm.querySelectorAll('img')].filter(x=>x.naturalWidth>0);
          return JSON.stringify({title:ti?ti.value:null, words:wc?wc[1]:null,
            imgsLoaded:imgs.length, emptyH1:[...pm.querySelectorAll('h1')].filter(h=>!h.textContent.trim()).length});})()"""))
        print("CLICK:", await ev("""(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='预览并发布');
          if(!b) return 'NO_BTN'; b.click(); return 'CLICKED';})()"""))
        await asyncio.sleep(6)
        print("AFTER:", await ev("""(()=>{const vis=[...document.querySelectorAll('[class*=dialog],[class*=modal],[role=dialog]')].filter(e=>e.offsetParent!==null);
          const txt=vis.map(e=>e.innerText.slice(0,200)).join(' || ');
          const cbs=[...document.querySelectorAll('input[type=checkbox]')].map(c=>c.checked);
          return JSON.stringify({url:location.href.slice(0,90), dialogs:vis.length, txt:txt.slice(0,300), checks:cbs,
            btns:[...document.querySelectorAll('button')].map(b=>b.textContent.trim()).filter(Boolean).slice(-12)});})()"""))
asyncio.run(main())
